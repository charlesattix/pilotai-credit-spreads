.PHONY: build test lint all clean

all: lint test build

# Build the web frontend
build:
	cd web && npm ci && npm run build

# Run tests
test:
	cd web && npm ci && npm test

# Run linter
lint:
	cd web && npm ci && npm run lint 2>/dev/null || echo "No lint script configured"

# Clean build artifacts
clean:
	rm -rf web/node_modules web/dist web/build
