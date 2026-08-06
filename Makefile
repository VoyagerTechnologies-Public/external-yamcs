# Makefile for SHIRE GSW (YAMCS)
.PHONY: all clean command-list command-send command-interactive container copy-comp-gsw-files help logs runtime start stop shell test timeline-list timeline-save timeline-load
.DEFAULT_GOAL := help

# Variables
# YAMCS_IMAGE is the GSW-specific build image. Kept separate from BUILD_IMAGE
# (which the top-level Makefile exports for FSW/sim) so it isn't shadowed.
YAMCS_IMAGE := ghcr.io/voyagertechnologies-public/shire-yamcs:latest
export MISSION ?= drm
export RUNTIME_GSW ?= shire-gsw-$(MISSION)
export SPACECRAFT ?= sat-1

# Main targets
help:
	@echo "SHIRE GSW (YAMCS) Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"; printf ""} /^[a-zA-Z_-]+:.*?##/ { printf "  %-20s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

all: runtime ## Build and prepare GSW for runtime

clean: stop ## Clean up GSW build artifacts and containers
	docker rmi $(RUNTIME_GSW):$(SPACECRAFT) 2>/dev/null || true
	docker volume rm gsw-data 2>/dev/null || true
	@rm -rf src/main/yamcs/mdb/components 2>/dev/null || true
	@rm -rf src/main/yamcs/displays/components 2>/dev/null || true
	@rm -rf src/main/yamcs/procedures/components 2>/dev/null || true

command-list: ## List all available YAMCS commands
	python3 yamcs_commander.py --list

command-send: ## Send a command (usage: make command-send CMD=/path/to/cmd ARGS="key=val,key2=val2")
	python3 yamcs_commander.py --command $(CMD) $(if $(ARGS),--args "$(ARGS)")

command-interactive: ## Start interactive command mode
	python3 yamcs_commander.py --interactive

container: Dockerfile.yamcs ## Pull or build the YAMCS base image (pulls from GHCR, builds locally if unavailable)
	@command -v docker >/dev/null 2>&1 || { echo "Error: docker is not installed or not in PATH."; exit 1; }
	@if docker pull $(YAMCS_IMAGE) 2>/dev/null; then \
		echo "[container] Pulled $(YAMCS_IMAGE) from GHCR"; \
	else \
		echo "[container] Building $(YAMCS_IMAGE) locally..."; \
		docker build -t $(YAMCS_IMAGE) -f Dockerfile.yamcs .; \
	fi

copy-comp-gsw-files: ## Copy component GSW files
	@mkdir -p src/main/yamcs/mdb/components
	@rm -rf src/main/yamcs/mdb/components/*
	@for comp_dir in ../comp/*/gsw; do \
		if [ -d "$$comp_dir" ]; then \
			comp_name=$$(basename $$(dirname "$$comp_dir")); \
			mkdir -p "src/main/yamcs/mdb/components/$$comp_name"; \
			cp -f "$$comp_dir"/* "src/main/yamcs/mdb/components/$$comp_name/" 2>/dev/null || true; \
		fi; \
	done
	@mkdir -p src/main/yamcs/displays/components
	@rm -rf src/main/yamcs/displays/components/*
	@for disp_dir in ../comp/*/gsw/displays; do \
		if [ -d "$$disp_dir" ]; then \
			comp_name=$$(basename $$(dirname $$(dirname "$$disp_dir"))); \
			mkdir -p "src/main/yamcs/displays/components/$$comp_name"; \
			cp -f "$$disp_dir"/* "src/main/yamcs/displays/components/$$comp_name/" 2>/dev/null || true; \
		fi; \
	done
	@mkdir -p src/main/yamcs/procedures/components
	@rm -rf src/main/yamcs/procedures/components/*
	@for proc_dir in ../comp/*/gsw/procedures; do \
		if [ -d "$$proc_dir" ]; then \
			comp_name=$$(basename $$(dirname $$(dirname "$$proc_dir"))); \
			mkdir -p "src/main/yamcs/procedures/components/$$comp_name"; \
			cp -f "$$proc_dir"/* "src/main/yamcs/procedures/components/$$comp_name/" 2>/dev/null || true; \
		fi; \
	done

logs: ## Show GSW container logs
	docker logs -f $(RUNTIME_GSW)

runtime: container copy-comp-gsw-files
	docker build -t $(RUNTIME_GSW):$(SPACECRAFT) -f Dockerfile.gsw --build-arg USER_ID=$(shell id -u) --build-arg GROUP_ID=$(shell id -g) .

start: ## Start GSW container
	docker run --rm -it \
		--name $(RUNTIME_GSW) \
		--network host \
		-p 8090:8090 \
		-v gsw-data:/app/yamcs-data \
		$(RUNTIME_GSW):$(SPACECRAFT)

shell: ## Get shell access to running GSW container
	docker exec -it $(RUNTIME_GSW) /bin/bash

stop: ## Stop and remove GSW container
	docker stop $(RUNTIME_GSW) 2>/dev/null || true
	docker rm $(RUNTIME_GSW) 2>/dev/null || true

test: ## Run tests
	docker run --rm -v $(CURDIR):$(CURDIR) -w $(CURDIR) --user $(shell id -u):$(shell id -g) $(YAMCS_IMAGE) ./mvnw test

timeline-list: ## List all timeline views
	python3 yamcs_timeline.py list

timeline-save: ## Save timelines (usage: make timeline-save FILE=backup.json)
	python3 yamcs_timeline.py save $(FILE)

timeline-load: ## Load timelines (usage: make timeline-load FILE=backup.json)
	python3 yamcs_timeline.py load $(FILE)
