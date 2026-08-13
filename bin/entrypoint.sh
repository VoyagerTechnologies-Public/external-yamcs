#!/usr/bin/env bash
set -euo pipefail

# Copy default displays and stacks into Yamcs data storage on first run
DATA_DIR=/app/yamcs-data

# Ensure storage bucket object directories exist (Yamcs expects 'objects/' inside each bucket)
mkdir -p "$DATA_DIR/storage/buckets/displays/objects"
mkdir -p "$DATA_DIR/storage/buckets/stacks/objects"

# If there are files directly under the bucket root (from older copies), move them into objects/
for b in displays stacks; do
  bucket_root="$DATA_DIR/storage/buckets/$b"
  bucket_objs="$bucket_root/objects"
  if [ -d "$bucket_root" ]; then
    # Move any files found at root (but not the objects dir) into objects/
    shopt -s nullglob 2>/dev/null || true
    for f in "$bucket_root"/*; do
      base=$(basename "$f")
      if [ "$base" != "objects" ]; then
        echo "Moving $f -> $bucket_objs/"
        mv -n "$f" "$bucket_objs/" 2>/dev/null || true
      fi
    done
  fi
done

# If displays/stacks packaged directories exist and buckets are empty, copy defaults into objects/
if [ -d /app/displays ] && [ -z "$(ls -A "$DATA_DIR/storage/buckets/displays/objects" 2>/dev/null)" ]; then
  echo "Populating default displays into $DATA_DIR/storage/buckets/displays/objects"
  cp -a /app/displays/* "$DATA_DIR/storage/buckets/displays/objects/" 2>/dev/null || true
  # Also copy any component display files (flatten component subdirs)
  cp -a /app/displays/components/* "$DATA_DIR/storage/buckets/displays/objects/" 2>/dev/null || true
  if [ -d /app/displays/components ]; then
    for f in /app/displays/components/*/*; do
      [ -f "$f" ] || continue
      cp -a "$f" "$DATA_DIR/storage/buckets/displays/objects/" 2>/dev/null || true
    done
  fi
fi

if [ -d /app/procedures ] && [ -z "$(ls -A "$DATA_DIR/storage/buckets/stacks/objects" 2>/dev/null)" ]; then
  echo "Populating default stacks into $DATA_DIR/storage/buckets/stacks/objects"
  cp -a /app/procedures/* "$DATA_DIR/storage/buckets/stacks/objects/" 2>/dev/null || true
  # Also copy any component procedure files (flatten component subdirs)
  cp -a /app/procedures/components/* "$DATA_DIR/storage/buckets/stacks/objects/" 2>/dev/null || true
  if [ -d /app/procedures/components ]; then
    for f in /app/procedures/components/*/*; do
      [ -f "$f" ] || continue
      cp -a "$f" "$DATA_DIR/storage/buckets/stacks/objects/" 2>/dev/null || true
    done
  fi
fi

# Start Yamcs in background so we can register objects through its storage API, then wait on it
/app/bin/yamcsd "$@" &
YAMCS_PID=$!

wait_for_api() {
  local retries=60
  local i=0
  echo "Waiting for Yamcs HTTP API to become available..."
  until curl -sS --fail "http://localhost:8090/api/" >/dev/null 2>&1; do
    i=$((i+1))
    if [ "$i" -ge "$retries" ]; then
      echo "Yamcs API did not become available after $retries attempts; proceeding without registering files"
      return 1
    fi
    sleep 1
  done
  echo "Yamcs HTTP API is available"
  return 0
}

register_bucket_files() {
  local bucket="$1"
  local dir="$DATA_DIR/storage/buckets/$bucket/objects"
  [ -d "$dir" ] || return 0
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    # Check if Yamcs already knows about this object
    status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8090/api/storage/buckets/$bucket/objects/$name" || true)
    if [ "$status" = "200" ]; then
      echo "$bucket/$name already registered (200)"
      continue
    fi
    echo "Registering $bucket/$name via storage API"
    # Use multipart upload (form) which has worked in this environment
    curl -sS -X POST -F "file=@$f" "http://localhost:8090/api/storage/buckets/$bucket/objects/$name" -o /dev/null || echo "Warning: upload of $name may have failed"
  done
}

if wait_for_api; then
  # Register displays and stacks (non-fatal on failures)
  register_bucket_files displays || true
  register_bucket_files stacks || true
  
  # Load timeline views if available (try multiple file locations)
  if [ -f /opt/yamcs/timelines/complete_timeline.json ]; then
    echo "Loading timeline views from /opt/yamcs/timelines/complete_timeline.json"
    python3 /opt/yamcs/yamcs_timeline.py load /opt/yamcs/timelines/complete_timeline.json || echo "Warning: timeline loading failed"
  elif [ -f /opt/yamcs/timelines/default.json ]; then
    echo "Loading timeline views from /opt/yamcs/timelines/default.json"
    python3 /opt/yamcs/yamcs_timeline.py load /opt/yamcs/timelines/default.json || echo "Warning: timeline loading failed"
  else
    echo "No timeline file found, skipping timeline loading"
  fi
else
  echo "Skipping storage API registration; Yamcs API not ready"
fi

# Wait for Yamcs process (forward signals)
wait "$YAMCS_PID"
