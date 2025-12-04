"""FastAPI application for open-claude-router."""

import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .config import config
from .stream import stream_openai_to_anthropic
from .transform import anthropic_to_openai, count_tokens, openai_to_anthropic

logger = logging.getLogger('uvicorn.error')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log startup configuration."""
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
    }
    url = f'{config.openrouter_base_url}/chat/completions'

    if is_streaming:
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
                        response, openai_request['model']
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
            anthropic_response = openai_to_anthropic(openai_data, openai_request['model'])
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
    """List available models from OpenRouter.

    Fetches and caches models from the OpenRouter API. Cache persists for
    the lifetime of the server process.

    Returns
        JSONResponse with OpenRouter models data structure.
    """
    from .models import get_models

    models = await get_models()
    return JSONResponse(content=models)


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
