"""FastAPI application for open-claude-router."""

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .config import config
from .stream import stream_openai_to_anthropic
from .transform import anthropic_to_openai, count_tokens, openai_to_anthropic

logger = logging.getLogger('uvicorn.error')

# Statsig cache path for serving cached evaluations
STATSIG_CACHE_DIR = Path.home() / '.claude' / 'statsig'
STATSIG_RESPONSE_FILE = Path(__file__).parent / 'statsig_response.json'


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize models and log startup configuration."""
    from .models import fetch_models, get_claude_aliases

    await fetch_models()
    aliases = get_claude_aliases()
    logger.info(f'Loaded {len(aliases)} Claude aliases: {aliases}')
    logger.info(f'Router ready on {config.host}:{config.port}')
    if config.model_override:
        logger.info(f'Model override: {config.model_override}')
    yield


app = FastAPI(
    title='Open Claude Router',
    description='API proxy that translates Anthropic Claude API to OpenAI-compatible APIs',
    version='1.0.0',
    lifespan=lifespan,
)


@app.get('/')
async def root() -> dict:
    """Health check endpoint.

    Returns service status, name, and version for monitoring and debugging.

    Returns
        Dict with 'status', 'service', and 'version' keys.
    """
    return {
        'status': 'ok',
        'service': 'open-claude-router',
        'version': '1.0.0',
    }


@app.post('/v1/messages', response_model=None)
async def messages(
    request: Request,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
) -> Response:
    """Proxy Anthropic-format messages to OpenRouter.

    Translates Anthropic Claude API requests to OpenAI format, forwards to
    OpenRouter, and converts responses back to Anthropic format. Supports
    both streaming (SSE) and non-streaming modes.

    API key priority: OPENROUTER_API_KEY env var > X-API-Key header > Bearer token.

    Args:
        request: FastAPI request containing Anthropic-format message body.
        x_api_key: Optional API key via X-API-Key header.
        authorization: Optional Bearer token for API authentication.

    Returns
        StreamingResponse for SSE or JSONResponse for non-streaming requests.
    """
    body = await request.json()

    api_key = (
        config.openrouter_api_key
        or x_api_key
        or (authorization.removeprefix('Bearer ') if authorization else None)
    )

    if not api_key:
        return JSONResponse(
            status_code=401,
            content={'error': {'message': 'API key required'}},
        )

    requested_model = body.get('model', 'unknown')
    openai_request = anthropic_to_openai(body, config.model_override)
    mapped_model = openai_request['model']
    is_streaming = openai_request.get('stream', False)

    logger.info(f'Request: {requested_model} -> {mapped_model} (stream={is_streaming})')

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com/tkellogg/open-claude-router',
        'X-Title': 'Open Claude Router',
    }
    url = f'{config.openrouter_base_url}/chat/completions'

    if is_streaming:
        # Estimate input tokens for message_start event
        estimated_input_tokens = count_tokens(body)

        async def generate():
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    'POST',
                    url,
                    headers=headers,
                    json=openai_request,
                    timeout=300.0,
                ) as response:
                    if not response.is_success:
                        error_text = await response.aread()
                        logger.error(f'Upstream error {response.status_code}: {error_text.decode()[:200]}')
                        yield f'data: {{"error": "{error_text.decode()}"}}\n\n'
                        return

                    async for chunk in stream_openai_to_anthropic(
                        response, requested_model, estimated_input_tokens
                    ):
                        yield chunk

        return StreamingResponse(
            generate(),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
            },
        )
    else:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json=openai_request,
                timeout=300.0,
            )

            if not response.is_success:
                logger.error(f'Upstream error {response.status_code}: {response.text[:200]}')
                return JSONResponse(
                    status_code=response.status_code,
                    content={'error': {'message': response.text}},
                )

            openai_data = response.json()
            anthropic_response = openai_to_anthropic(openai_data, requested_model)
            return JSONResponse(content=anthropic_response)


@app.post('/v1/messages/count_tokens')
async def count_tokens_endpoint(request: Request) -> JSONResponse:
    """Estimate token count for an Anthropic-format request.

    Uses a heuristic of ~4 characters per token to provide a quick estimate
    without calling the actual tokenizer.

    Args:
        request: FastAPI request containing Anthropic-format message body.

    Returns
        JSONResponse with 'input_tokens' count.
    """
    body = await request.json()
    input_tokens = count_tokens(body)
    return JSONResponse(content={'input_tokens': input_tokens})


@app.get('/v1/models')
async def list_models() -> JSONResponse:
    """List available models in Anthropic format.

    Fetches models from OpenRouter and converts to Anthropic's format.

    Returns
        JSONResponse with Anthropic-compatible models data structure.
    """
    from datetime import datetime, timezone

    from .models import get_models

    openrouter_models = await get_models()

    # Convert to Anthropic format
    anthropic_models = []
    for model in openrouter_models.get('data', []):
        # Convert Unix timestamp to RFC 3339
        created = model.get('created', 0)
        if created:
            created_at = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        else:
            created_at = datetime.now(tz=timezone.utc).isoformat()

        anthropic_models.append({
            'id': model.get('id', ''),
            'created_at': created_at,
            'display_name': model.get('name', model.get('id', '')),
            'type': 'model',
        })

    return JSONResponse(content={
        'data': anthropic_models,
        'has_more': False,
        'first_id': anthropic_models[0]['id'] if anthropic_models else None,
        'last_id': anthropic_models[-1]['id'] if anthropic_models else None,
    })


# ============================================================================
# Statsig stub endpoints - bypass telemetry validation
# ============================================================================

def _load_statsig_response() -> dict | None:
    """Load statsig response from bundled file or user cache."""
    # First try bundled response file
    if STATSIG_RESPONSE_FILE.exists():
        try:
            with STATSIG_RESPONSE_FILE.open() as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f'Failed to load bundled statsig response: {e}')

    # Fall back to user's cached evaluations
    try:
        for cache_file in STATSIG_CACHE_DIR.glob('statsig.cached.evaluations.*'):
            with Path(cache_file).open() as f:
                cached = json.load(f)
                if 'data' in cached:
                    return json.loads(cached['data'])
    except Exception as e:
        logger.warning(f'Failed to load statsig cache: {e}')

    return None


def _make_statsig_response(user: dict | None = None) -> dict:
    """Generate a valid statsig initialize response."""
    cached = _load_statsig_response()
    if cached:
        # Update timestamp to current time
        cached['time'] = int(time.time() * 1000)
        if user:
            cached['evaluated_keys'] = user
        return cached

    # Minimal valid response if no cache
    return {
        'feature_gates': {},
        'dynamic_configs': {},
        'layer_configs': {},
        'sdkParams': {},
        'has_updates': True,
        'generator': 'open-claude-router',
        'time': int(time.time() * 1000),
        'evaluated_keys': user or {},
        'hash_used': 'djb2',
    }


@app.post('/v1/initialize')
async def statsig_initialize(request: Request) -> JSONResponse:
    """Statsig initialize endpoint - returns feature flags."""
    body = await request.json()
    user = body.get('user', {})
    logger.info('Statsig initialize request (stubbed)')
    return JSONResponse(content=_make_statsig_response(user))


@app.post('/v1/log_event')
async def statsig_log_event(request: Request) -> JSONResponse:
    """Statsig log event endpoint - accepts and discards events."""
    logger.debug('Statsig log_event request (stubbed)')
    return JSONResponse(content={'success': True})


@app.post('/v1/rgstr')
async def statsig_rgstr(request: Request) -> JSONResponse:
    """Statsig register endpoint - accepts and discards."""
    logger.debug('Statsig rgstr request (stubbed)')
    return JSONResponse(content={'success': True})


@app.post('/v1/get_id_lists')
async def statsig_get_id_lists(request: Request) -> JSONResponse:
    """Statsig ID lists endpoint."""
    logger.debug('Statsig get_id_lists request (stubbed)')
    return JSONResponse(content={})


# ============================================================================
# Models endpoints
# ============================================================================

@app.get('/v1/models/{model_id}')
async def get_model(model_id: str) -> JSONResponse:
    """Get a specific model in Anthropic format."""
    from datetime import datetime, timezone

    from .models import get_models, map_model

    openrouter_models = await get_models()

    # Find the model (also check mapped version)
    mapped_id = map_model(model_id)
    for model in openrouter_models.get('data', []):
        if model.get('id') in {model_id, mapped_id}:
            created = model.get('created', 0)
            if created:
                created_at = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
            else:
                created_at = datetime.now(tz=timezone.utc).isoformat()

            return JSONResponse(content={
                'id': model_id,  # Return the original requested ID, not OpenRouter's
                'created_at': created_at,
                'display_name': model.get('name', model.get('id', '')),
                'type': 'model',
            })

    # Return a synthetic model if not found (allows any model to be "valid")
    return JSONResponse(content={
        'id': model_id,
        'created_at': datetime.now(tz=timezone.utc).isoformat(),
        'display_name': model_id,
        'type': 'model',
    })


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def catch_all(path: str, request: Request):
    """Handle unimplemented endpoints gracefully."""
    logger.debug(f'Unhandled: {request.method} /{path}')
    return JSONResponse(status_code=404, content={'error': {'message': f'Not found: /{path}'}})


def run() -> None:
    """Run the server."""
    uvicorn.run(
        'src.main:app',
        host=config.host,
        port=config.port,
        reload=True,
    )


if __name__ == '__main__':
    run()
