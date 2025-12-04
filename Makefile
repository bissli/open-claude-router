.PHONY: install start stop status logs test build run clean help

# Default target
help:
	@echo "open-claude-router commands:"
	@echo ""
	@echo "  make install    Install dependencies"
	@echo "  make start      Start server in foreground"
	@echo "  make start-bg   Start server in background"
	@echo "  make stop       Stop background server"
	@echo "  make status     Check server status"
	@echo "  make logs       Show recent logs"
	@echo "  make logs-f     Follow logs in real-time"
	@echo "  make test       Run tests"
	@echo "  make build      Build Docker image"
	@echo "  make run        Run with Docker"
	@echo "  make clean      Clean up generated files"

# Installation
install:
	poetry install

# Server management
start:
	poetry run python -m src.main

start-bg:
	@poetry run python -m src.main > .router.log 2>&1 & echo $$! > .router.pid
	@echo "Server started (PID: $$(cat .router.pid))"
	@echo "Logs: .router.log"

stop:
	@if [ -f .router.pid ]; then \
		kill $$(cat .router.pid) 2>/dev/null && echo "Server stopped" || echo "Server not running"; \
		rm -f .router.pid; \
	else \
		echo "No PID file found"; \
	fi

status:
	@if [ -f .router.pid ] && kill -0 $$(cat .router.pid) 2>/dev/null; then \
		echo "Server is running (PID: $$(cat .router.pid))"; \
	else \
		echo "Server is not running"; \
		rm -f .router.pid 2>/dev/null; \
	fi

logs:
	@if [ -f .router.log ]; then tail -50 .router.log; else echo "No log file"; fi

logs-f:
	@if [ -f .router.log ]; then tail -f .router.log; else echo "No log file"; fi

# Testing
test:
	poetry run pytest -v

test-cov:
	poetry run pytest --cov=src --cov-report=term-missing

# Docker
build:
	docker build -t open-claude-router .

run:
	docker run -p 8787:8787 \
		-e OPENROUTER_API_KEY=$${OPENROUTER_API_KEY} \
		-e MODEL_OVERRIDE=$${MODEL_OVERRIDE:-} \
		open-claude-router

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

# Cleanup
clean:
	rm -f .router.pid .router.log
	rm -rf __pycache__ .pytest_cache .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
