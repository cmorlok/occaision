#!/usr/bin/env bash
#
# agy-container.sh - Wrapper script to run Antigravity CLI (agy) inside the Dev Container from the Host.
#

set -e

CONTAINER_NAME="seller-devcontainer"
LABEL_FILTER="devcontainer.app=seller"

# Determine workspace directory (root of the repo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check if docker is installed on the host
if ! command -v docker &>/dev/null; then
    echo "Error: 'docker' command not found on host. Please ensure Docker is installed and in your PATH." >&2
    exit 1
fi

# Determine TTY flags
if [ -t 0 ] && [ -t 1 ]; then
    DOCKER_FLAGS="-it"
else
    DOCKER_FLAGS="-i"
fi

# 1. Try to find running container by name or label
TARGET_CONTAINER=""

if docker ps --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
    TARGET_CONTAINER="$CONTAINER_NAME"
else
    # Check by label
    LABEL_MATCH="$(docker ps --filter "label=${LABEL_FILTER}" --format '{{.ID}}' | head -n 1)"
    if [ -n "$LABEL_MATCH" ]; then
        TARGET_CONTAINER="$LABEL_MATCH"
    else
        # Check by devcontainer workspace folder label
        FOLDER_MATCH="$(docker ps --filter "label=devcontainer.local_folder=${WORKSPACE_DIR}" --format '{{.ID}}' | head -n 1)"
        if [ -n "$FOLDER_MATCH" ]; then
            TARGET_CONTAINER="$FOLDER_MATCH"
        fi
    fi
fi

# 2. If running, execute agy inside it
if [ -n "$TARGET_CONTAINER" ]; then
    exec docker exec $DOCKER_FLAGS -u developer -w /workspaces/$(basename "$WORKSPACE_DIR") "$TARGET_CONTAINER" agy "$@" 2>/dev/null \
      || exec docker exec $DOCKER_FLAGS -u developer -w /app "$TARGET_CONTAINER" agy "$@"
fi

# 3. If container exists but is stopped, start it
STOPPED_CONTAINER="$(docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | head -n 1)"
if [ -n "$STOPPED_CONTAINER" ]; then
    echo "Container '${CONTAINER_NAME}' is stopped. Starting container..."
    docker start "$STOPPED_CONTAINER" >/dev/null
    exec docker exec $DOCKER_FLAGS -u developer "$STOPPED_CONTAINER" agy "$@"
fi

# 4. If no container was found
echo "Dev Container '${CONTAINER_NAME}' is not running."
echo "Please start the Dev Container in VS Code ('Dev Containers: Reopen in Container')."
echo ""
echo "Alternatively, you can build and run a one-off instance with:"
echo "  docker build -f \"$WORKSPACE_DIR/.devcontainer/Dockerfile\" -t seller-devcontainer \"$WORKSPACE_DIR\""
echo "  docker run $DOCKER_FLAGS --rm -v \"$WORKSPACE_DIR\":/app -v seller-devcontainer-home:/home/developer -w /app -u developer seller-devcontainer agy \"$@\""
exit 1
