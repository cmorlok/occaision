.PHONY: test test-extension build-extension build-docker help

help:
	@echo "OccAIsion Development Targets:"
	@echo "  make test             - Run automated pytest suite via scripts/test.sh"
	@echo "  make test-extension   - Build extension package for verification"
	@echo "  make build-extension  - Build Firefox WebExtension (dist/occaision.zip)"
	@echo "  make build-docker     - Build Docker image (occaision:latest)"

test:
	@bash scripts/test.sh $(ARGS)

test-extension:
	@bash scripts/build_extension.sh

build-extension:
	@bash scripts/build_extension.sh

build-docker:
	@bash scripts/build_docker.sh
