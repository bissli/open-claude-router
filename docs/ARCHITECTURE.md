# Architecture

This document explains how open-claude-router enables Claude Code to work without a direct Anthropic API key.

## Overview

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────┐     ┌─────────────┐
│ Claude Code │────►│ Router (port 8787)  │────►│ OpenRouter  │────►│ Claude/GPT/ │
│             │◄────│                     │◄────│             │◄────│ Grok/etc.   │
└─────────────┘     └─────────────────────┘     └─────────────┘     └─────────────┘
       │                     │
       │                     ├── API Translation (Anthropic ↔ OpenAI)
       │                     ├── Statsig Stubs (telemetry bypass)
       │                     └── Model Mapping
       │
       └── Configured via ~/.claude/settings.json
```

## How It Works

### 1. The Core Trick: `ANTHROPIC_BASE_URL`

Claude Code is an HTTP client that reads `ANTHROPIC_BASE_URL` to determine where to send requests. By setting:

```json
"ANTHROPIC_BASE_URL": "http://localhost:8787"
```

**All requests** - API calls, model lookups, and telemetry - go to our local router instead of Anthropic's servers.

### 2. The Fake API Key

```json
"ANTHROPIC_API_KEY": "sk-ant-fake-key"
```

Claude Code doesn't validate the API key locally - it just needs *something* that looks like a key. The actual authentication happens when our router forwards requests to OpenRouter using the **real** `OPENROUTER_API_KEY`.

### 3. Request Flow

```
Claude Code
    │
    ├─► POST /v1/messages (Anthropic format)
    │         │
    │         ▼
    │   Router receives request
    │         │
    │         ├─► anthropic_to_openai() transforms the request
    │         ├─► Adds real OPENROUTER_API_KEY header
    │         ├─► Forwards to openrouter.ai/api/v1/chat/completions
    │         │
    │         ▼
    │   OpenRouter responds (OpenAI format)
    │         │
    │         ├─► openai_to_anthropic() transforms response
    │         │
    │         ▼
    │   Response (Anthropic format)
    │
    └─► Claude Code displays it
```

### 4. Statsig Telemetry Stubs

Claude Code uses [Statsig](https://statsig.com/) for feature flags and telemetry. Without proper responses, Claude Code would hang or fail. Our router stubs these endpoints:

| Endpoint | Purpose | Our Response |
|----------|---------|--------------|
| `POST /v1/initialize` | Fetch feature flags at startup | Returns cached/minimal flags |
| `POST /v1/log_event` | Send usage telemetry | Accepts and discards (returns `{"success": true}`) |
| `POST /v1/rgstr` | Register telemetry events | Accepts and discards |
| `POST /v1/get_id_lists` | Get experiment ID lists | Returns empty object |

These stubs are implemented in `src/main.py:259-286`.

### 5. DNS-Level Blocking

Some Claude Code components may have hardcoded Anthropic URLs. The `/etc/hosts` file redirects these to localhost:

```
127.0.0.1 api.anthropic.com
127.0.0.1 statsig.anthropic.com
127.0.0.1 sentry.anthropic.com
```

This ensures even hardcoded requests hit the local router.

## API Translation

The router translates between Anthropic's API format and OpenAI's format.

### Request Translation (`anthropic_to_openai`)

| Anthropic Field | OpenAI Field |
|-----------------|--------------|
| `model` | `model` (mapped to OpenRouter model ID) |
| `messages` | `messages` (content blocks → string/array) |
| `system` | Prepended as system message |
| `max_tokens` | `max_tokens` |
| `temperature` | `temperature` |
| `stream` | `stream` |
| `tools` | `tools` (function calling format) |

### Response Translation (`openai_to_anthropic`)

| OpenAI Field | Anthropic Field |
|--------------|-----------------|
| `choices[0].message.content` | `content` (as text blocks) |
| `choices[0].message.tool_calls` | `content` (as tool_use blocks) |
| `usage.prompt_tokens` | `usage.input_tokens` |
| `usage.completion_tokens` | `usage.output_tokens` |
| `choices[0].finish_reason` | `stop_reason` |

### Model Mapping

Claude model names are mapped to OpenRouter equivalents:

| Claude Code Requests | OpenRouter Model |
|---------------------|------------------|
| `claude-sonnet-4-*` | `anthropic/claude-sonnet-4` |
| `claude-opus-4*` | `anthropic/claude-opus-4` |
| `claude-3-5-sonnet-*` | `anthropic/claude-3.5-sonnet` |
| `claude-3-5-haiku-*` | `anthropic/claude-3.5-haiku` |

The `MODEL_OVERRIDE` environment variable can force all requests to a specific model.

## Project Structure

```
├── router                  # Bash script for Docker container management
├── src/
│   ├── main.py             # FastAPI application
│   │   ├── /v1/messages    # Main API endpoint
│   │   ├── /v1/models      # Model listing
│   │   └── /v1/initialize  # Statsig stubs
│   ├── config.py           # Environment configuration
│   ├── models.py           # Model fetching and mapping
│   ├── transform.py        # Anthropic ↔ OpenAI translation
│   └── stream.py           # Server-Sent Events (SSE) streaming
├── Dockerfile
└── pyproject.toml
```

## Session Persistence

The setup survives Claude Code restarts and logouts because:

1. **Settings are persistent**: `~/.claude/settings.json` is read on every startup
2. **No server-side session**: The "session" is entirely local - Claude Code just needs valid-looking responses
3. **Router is stateless**: Each request is independent; no session state required

As long as the router is running and settings.json has the env block, Claude Code will work.

## Security Considerations

- **API Key Isolation**: Your real OpenRouter key is only used server-side by the router. Claude Code never sees it.
- **No Data to Anthropic**: With `/etc/hosts` blocking, no data reaches Anthropic's servers.
- **Local-First**: All processing happens on your machine; the router is just a translation layer.

## Supported Features

| Feature | Status |
|---------|--------|
| Chat completions | ✅ |
| Streaming (SSE) | ✅ |
| Tool/function calling | ✅ |
| Model listing | ✅ |
| Token counting | ✅ (estimated) |
| Extended thinking | ✅ (via OpenRouter) |
| Image inputs | ✅ |
| PDF inputs | ✅ |

## Limitations

- **Token counting is estimated**: Uses ~4 chars/token heuristic, not actual tokenizer
- **Some Anthropic-specific features may not translate**: Beta features or new API additions may need updates
- **Depends on OpenRouter availability**: If OpenRouter is down, requests fail
