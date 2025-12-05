"""Streaming SSE transformation from OpenAI to Anthropic format."""

import json
import logging
import time
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger('uvicorn.error')


def _sse_event(event_type: str, data: dict) -> str:
    """Format a server-sent event."""
    return f'event: {event_type}\ndata: {json.dumps(data)}\n\n'


async def stream_openai_to_anthropic(
    response: httpx.Response, model: str, input_tokens: int = 0
) -> AsyncIterator[str]:
    """Transform OpenAI streaming response to Anthropic SSE format.

    Args:
        response: The httpx streaming response from OpenRouter
        model: The model name to include in the response
        input_tokens: Estimated input token count for message_start
    """
    message_id = f'msg_{int(time.time() * 1000)}'

    yield _sse_event('message_start', {
        'type': 'message_start',
        'message': {
            'id': message_id,
            'type': 'message',
            'role': 'assistant',
            'content': [],
            'model': model,
            'stop_reason': None,
            'stop_sequence': None,
            'usage': {'input_tokens': input_tokens, 'output_tokens': 1},
        },
    })

    content_block_index = 0
    has_started_text_block = False
    has_started_thinking_block = False
    is_tool_use = False
    current_tool_call_id: str | None = None
    tool_call_json: dict[str, str] = {}
    usage: dict[str, int] = {}

    def close_current_block() -> str:
        """Generate content_block_stop event."""
        return _sse_event('content_block_stop', {
            'type': 'content_block_stop',
            'index': content_block_index,
        })

    async for line in response.aiter_lines():
        if not line or not line.startswith('data: '):
            continue

        data_str = line[6:].strip()
        if data_str == '[DONE]':
            continue

        try:
            parsed = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        if parsed.get('usage'):
            usage = parsed['usage']

        choices = parsed.get('choices', [])
        if not choices:
            continue

        delta = choices[0].get('delta', {})
        if not delta:
            continue

        if delta.get('tool_calls'):
            for tool_call in delta['tool_calls']:
                tool_call_id = tool_call.get('id')

                if tool_call_id and tool_call_id != current_tool_call_id:
                    if is_tool_use or has_started_text_block or has_started_thinking_block:
                        yield close_current_block()

                    is_tool_use = True
                    has_started_text_block = False
                    has_started_thinking_block = False
                    current_tool_call_id = tool_call_id
                    content_block_index += 1
                    tool_call_json[tool_call_id] = ''

                    yield _sse_event('content_block_start', {
                        'type': 'content_block_start',
                        'index': content_block_index,
                        'content_block': {
                            'type': 'tool_use',
                            'id': tool_call_id,
                            'name': tool_call.get('function', {}).get('name'),
                            'input': {},
                        },
                    })

                func_args = tool_call.get('function', {}).get('arguments')
                if func_args and current_tool_call_id:
                    tool_call_json[current_tool_call_id] += func_args
                    yield _sse_event('content_block_delta', {
                        'type': 'content_block_delta',
                        'index': content_block_index,
                        'delta': {
                            'type': 'input_json_delta',
                            'partial_json': func_args,
                        },
                    })

        elif delta.get('reasoning'):
            if is_tool_use or has_started_text_block:
                yield close_current_block()
                is_tool_use = False
                has_started_text_block = False
                current_tool_call_id = None
                content_block_index += 1

            if not has_started_thinking_block:
                yield _sse_event('content_block_start', {
                    'type': 'content_block_start',
                    'index': content_block_index,
                    'content_block': {
                        'type': 'thinking',
                        'thinking': '',
                        'signature': 'openrouter-reasoning',
                    },
                })
                has_started_thinking_block = True

            yield _sse_event('content_block_delta', {
                'type': 'content_block_delta',
                'index': content_block_index,
                'delta': {
                    'type': 'thinking_delta',
                    'thinking': delta['reasoning'],
                },
            })

        elif delta.get('content'):
            if is_tool_use or has_started_thinking_block:
                yield close_current_block()
                is_tool_use = False
                has_started_thinking_block = False
                current_tool_call_id = None
                content_block_index += 1

            if not has_started_text_block:
                yield _sse_event('content_block_start', {
                    'type': 'content_block_start',
                    'index': content_block_index,
                    'content_block': {'type': 'text', 'text': ''},
                })
                has_started_text_block = True

            yield _sse_event('content_block_delta', {
                'type': 'content_block_delta',
                'index': content_block_index,
                'delta': {
                    'type': 'text_delta',
                    'text': delta['content'],
                },
            })

    if is_tool_use or has_started_text_block or has_started_thinking_block:
        yield close_current_block()

    yield _sse_event('message_delta', {
        'type': 'message_delta',
        'delta': {
            'stop_reason': 'tool_use' if is_tool_use else 'end_turn',
            'stop_sequence': None,
        },
        'usage': {
            'output_tokens': usage.get('completion_tokens', 0),
        },
    })

    yield _sse_event('message_stop', {'type': 'message_stop'})
