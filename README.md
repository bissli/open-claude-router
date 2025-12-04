# open-claude-router

An API proxy that translates between Anthropic's Claude API and OpenAI-compatible APIs, enabling you to use Claude Code with OpenRouter and other OpenAI-compatible providers.

## Features

- **Local-First**: Designed to run locally on your machine for maximum privacy and control.
- **Model Override**: Force specific models (like Grok, Gemini, etc.) via environment variables without changing Claude Code settings.
- **API Key Override**: Use a separate OpenRouter API key for the router while keeping your Anthropic key in Claude Code settings.
- **Reasoning Support**: Full support for OpenRouter's reasoning capabilities (e.g., DeepSeek R1).
- **Dynamic Models**: Fetches available models directly from OpenRouter API.

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/bissli/open-claude-router.git
cd open-claude-router

# Install with Poetry (Python 3.10+)
poetry install
```

### 2. Configuration

Create a `.env` file in the project root:

```ini
# Your OpenRouter API Key
OPENROUTER_API_KEY=sk-or-...

# Force the router to use this model (optional)
MODEL_OVERRIDE=x-ai/grok-4.1-fast
```

### 3. Run the Router

```bash
# Using Make (recommended)
make start             # Start in foreground
make start-bg          # Start in background
make stop              # Stop background server
make status            # Check server status
make logs              # Show recent logs
make logs-f            # Follow logs

# Or run directly
python -m src.main

# Or use the entry point
open-claude-router
```

The router will start at `http://localhost:8787`.

### 4. Configure Claude Code

```bash
export ANTHROPIC_BASE_URL="http://localhost:8787"
export ANTHROPIC_API_KEY="sk-dummy-key"  # Can be anything if OPENROUTER_API_KEY is set
claude
```

## Docker

### Build and Run

```bash
# Build the image
docker build -t open-claude-router .

# Run with environment variables
docker run -p 8787:8787 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -e MODEL_OVERRIDE=x-ai/grok-4.1-fast \
  open-claude-router
```

### Docker Compose

```bash
# Create .env file with your settings
cp .env.example .env
# Edit .env with your API key

# Start the service
docker-compose up -d

# Stop the service
docker-compose down
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/v1/messages` | POST | Main chat endpoint (Anthropic format) |
| `/v1/messages/count_tokens` | POST | Token estimation |
| `/v1/models` | GET | List available models from OpenRouter |

## Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key | None |
| `OPENROUTER_BASE_URL` | API base URL | `https://openrouter.ai/api/v1` |
| `MODEL_OVERRIDE` | Force specific model | None |
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `8787` |

## Development

### Running Tests

```bash
# Install dev dependencies
poetry install

# Run tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src
```

### Project Structure

```
src/
├── __init__.py
├── main.py          # FastAPI application
├── cli.py           # Server management CLI
├── config.py        # Configuration management
├── models.py        # Model loading from OpenRouter API
├── transform.py     # Request/response transformations
└── stream.py        # SSE streaming handler

tests/
├── test_transform.py  # Unit tests
└── test_api.py        # Integration tests
```

## Thanks

Special thanks to these projects that inspired open-claude-router:

- [claude-code-router](https://github.com/musistudio/claude-code-router)
- [claude-code-proxy](https://github.com/kiyo-e/claude-code-proxy)

## License

MIT
