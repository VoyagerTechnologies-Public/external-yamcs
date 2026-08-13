#!/bin/bash
# Load saved YAMCS timelines after startup
# Usage: ./load_timelines.sh [timeline_file.json]

TIMELINE_FILE="${1:-timelines/default.json}"
YAMCS_URL="http://localhost:8090"
MAX_ATTEMPTS=30
SLEEP_TIME=2

echo "Waiting for YAMCS to be ready..."

# Wait for YAMCS to be accessible
for i in $(seq 1 $MAX_ATTEMPTS); do
    if curl -s -f "$YAMCS_URL/api/archive/shire" > /dev/null 2>&1; then
        echo "✓ YAMCS is ready!"
        break
    fi
    
    if [ $i -eq $MAX_ATTEMPTS ]; then
        echo "✗ YAMCS did not become ready in time"
        exit 1
    fi
    
    echo "  Attempt $i/$MAX_ATTEMPTS - waiting ${SLEEP_TIME}s..."
    sleep $SLEEP_TIME
done

# Wait a bit more for timeline service to initialize
sleep 3

# Load timelines if file exists
if [ -f "$TIMELINE_FILE" ]; then
    echo "Loading timelines from $TIMELINE_FILE..."
    python3 /opt/yamcs/yamcs_timeline.py load "$TIMELINE_FILE"
else
    echo "No timeline file found at $TIMELINE_FILE, skipping..."
fi
