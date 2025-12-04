#!/bin/bash
#
# open-claude-router - Start/stop the router Docker container
#
# Usage:
#   router.sh start    Start the router
#   router.sh stop     Stop the router
#   router.sh restart  Restart the router
#   router.sh status   Check if running
#   router.sh logs     Show recent logs
#   router.sh logs -f  Follow logs
#

CONTAINER_NAME="open-claude-router"
IMAGE_NAME="open-claude-router"
PORT="${ROUTER_PORT:-8787}"

start() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Router is already running"
        return 0
    fi

    # Remove stopped container if exists
    docker rm "$CONTAINER_NAME" 2>/dev/null

    echo "Starting router on port $PORT..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        -p "${PORT}:8787" \
        -e OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
        -e OPENROUTER_BASE_URL="${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}" \
        -e MODEL_OVERRIDE="${MODEL_OVERRIDE:-}" \
        -e HOST=0.0.0.0 \
        --restart unless-stopped \
        "$IMAGE_NAME"

    if [ $? -eq 0 ]; then
        echo "Router started at http://localhost:${PORT}"
    else
        echo "Failed to start router"
        return 1
    fi
}

stop() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Router is not running"
        return 0
    fi

    echo "Stopping router..."
    docker stop "$CONTAINER_NAME"
    docker rm "$CONTAINER_NAME" 2>/dev/null
    echo "Router stopped"
}

restart() {
    stop
    sleep 1
    start
}

status() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Router is running"
        docker ps --filter "name=${CONTAINER_NAME}" --format "  Container: {{.Names}}\n  Port: {{.Ports}}\n  Status: {{.Status}}"
    else
        echo "Router is not running"
        return 1
    fi
}

logs() {
    if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Container not found"
        return 1
    fi

    if [ "$1" = "-f" ]; then
        docker logs -f "$CONTAINER_NAME"
    else
        docker logs --tail 50 "$CONTAINER_NAME"
    fi
}

usage() {
    echo "Usage: $0 {start|stop|restart|status|logs [-f]}"
    echo ""
    echo "Environment variables:"
    echo "  OPENROUTER_API_KEY    Your OpenRouter API key (required)"
    echo "  MODEL_OVERRIDE        Force a specific model (optional)"
    echo "  ROUTER_PORT           Port to expose (default: 8787)"
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "$2"
        ;;
    *)
        usage
        exit 1
        ;;
esac
