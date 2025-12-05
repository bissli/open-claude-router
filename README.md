# open-claude-router

An API proxy that lets you run Claude Code with OpenRouter (or any OpenAI-compatible provider) instead of a direct Anthropic API key.

## Quick Start

### 1. Configure Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8787",
    "NODE_TLS_REJECT_UNAUTHORIZED": "0",
    "ANTHROPIC_API_KEY": "sk-ant-fake-key"
  }
}
```

### 2. Set Your OpenRouter API Key

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

Get your key from [openrouter.ai/keys](https://openrouter.ai/keys).

### 3. Start the Router

```bash
git clone https://github.com/tkellogg/open-claude-router.git
cd open-claude-router
./router start
```

### 4. Run Claude Code

```bash
claude
```

That's it! See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details on how it works.

## Router Commands

```bash
./router start      # Start the router container
./router stop       # Stop the router
./router restart    # Restart the router
./router status     # Check if running
./router logs       # Show recent logs
./router logs -f    # Follow logs in real-time
./router clean      # Remove container and image
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key | Required |
| `MODEL_OVERRIDE` | Force a specific model for all requests | None |
| `ROUTER_PORT` | Port to expose the router | `8787` |
| `OPENROUTER_BASE_URL` | OpenRouter API endpoint | `https://openrouter.ai/api/v1` |

### Model Override

Force all requests to use a specific model:

```bash
export MODEL_OVERRIDE="x-ai/grok-3-fast"
./router start
```

## Blocking Anthropic Telemetry

To fully block connections to Anthropic servers:

```bash
sudo tee -a /etc/hosts << 'EOF'

# Block Anthropic telemetry (open-claude-router)
127.0.0.1 api.anthropic.com
127.0.0.1 statsig.anthropic.com
127.0.0.1 sentry.anthropic.com
EOF
```

To remove the block:

```bash
sudo sed -i '/Block Anthropic telemetry/,+4d' /etc/hosts
```

## Running Without Docker

```bash
# With Poetry
poetry install
poetry run python -m src.main

# With Make
make start          # Foreground
make start-bg       # Background
make stop           # Stop
```

## Troubleshooting

### Claude Code won't start

Ensure `~/.claude/settings.json` has the `env` block shown above.

### Router not receiving requests

```bash
./router status
curl http://localhost:8787/
```

### OpenRouter errors

```bash
echo $OPENROUTER_API_KEY
./router logs
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - How the key faking and API translation works

## Thanks

Inspired by:
- [claude-code-router](https://github.com/musistudio/claude-code-router)
- [claude-code-proxy](https://github.com/kiyo-e/claude-code-proxy)

## License

MIT
