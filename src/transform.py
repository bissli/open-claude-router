"""Transform requests/responses between Anthropic and OpenAI formats."""

import json
import time
from typing import Any

from .models import map_model


def _validate_tool_calls(messages: list[dict]) -> list[dict]:
    """Validate OpenAI messages to ensure complete tool_calls/tool pairing.

    Requires tool messages to immediately follow assistant messages with tool_calls.
    """
    validated: list[dict] = []

    for i, msg in enumerate(messages):
        current = msg.copy()

        if current.get('role') == 'assistant' and current.get('tool_calls'):
            immediate_tool_msgs: list[dict] = []
            j = i + 1
            while j < len(messages) and messages[j].get('role') == 'tool':
                immediate_tool_msgs.append(messages[j])
                j += 1

            tool_msg_ids = {m.get('tool_call_id') for m in immediate_tool_msgs}
            valid_calls = [
                tc for tc in current['tool_calls'] if tc.get('id') in tool_msg_ids
            ]

            if valid_calls:
                current['tool_calls'] = valid_calls
            else:
                del current['tool_calls']

            if current.get('content') or current.get('tool_calls'):
                validated.append(current)

        elif current.get('role') == 'tool':
            has_match = False
            if i > 0:
                for k in range(i - 1, -1, -1):
                    prev = messages[k]
                    if prev.get('role') == 'tool':
                        continue
                    if prev.get('role') == 'assistant' and prev.get('tool_calls'):
                        has_match = any(
                            tc.get('id') == current.get('tool_call_id')
                            for tc in prev['tool_calls']
                        )
                    break

            if has_match:
                validated.append(current)
        else:
            validated.append(current)

    return validated


def anthropic_to_openai(body: dict, model_override: str | None = None) -> dict:
    """Convert Anthropic API request to OpenAI format."""
    model = model_override or map_model(body.get('model', ''))
    messages = body.get('messages', [])
    system = body.get('system', [])
    tools = body.get('tools')
    stream = body.get('stream', False)
    temperature = body.get('temperature')
    reasoning = body.get('reasoning')
    reasoning_effort = body.get('reasoning_effort')
    thinking = body.get('thinking')
    max_tokens = body.get('max_tokens')
    top_p = body.get('top_p')
    top_k = body.get('top_k')
    stop_sequences = body.get('stop_sequences')
    tool_choice = body.get('tool_choice')

    system_messages: list[dict] = []
    if isinstance(system, str):
        content: list[dict[str, Any]] = [{'type': 'text', 'text': system}]
        if 'claude' in model:
            content[0]['cache_control'] = {'type': 'ephemeral'}
        system_messages.append({'role': 'system', 'content': content})
    elif isinstance(system, list):
        for item in system:
            content = [{'type': 'text', 'text': item.get('text', '')}]
            if 'claude' in model:
                content[0]['cache_control'] = {'type': 'ephemeral'}
            system_messages.append({'role': 'system', 'content': content})

    openai_messages: list[dict] = []
    for msg in messages:
        role = msg.get('role')
        content = msg.get('content')

        if not isinstance(content, list):
            if isinstance(content, str):
                openai_messages.append({'role': role, 'content': content})
            continue

        if role == 'assistant':
            assistant_msg: dict[str, Any] = {'role': 'assistant', 'content': None}
            text_parts: list[str] = []
            tool_calls: list[dict] = []

            for part in content:
                if part.get('type') == 'text':
                    text = part.get('text', '')
                    text_parts.append(text if isinstance(text, str) else json.dumps(text))
                elif part.get('type') == 'tool_use':
                    tool_calls.append({
                        'id': part.get('id'),
                        'type': 'function',
                        'function': {
                            'name': part.get('name'),
                            'arguments': json.dumps(part.get('input', {})),
                        },
                    })

            text_content = '\n'.join(text_parts).strip()
            if text_content:
                assistant_msg['content'] = text_content
            if tool_calls:
                assistant_msg['tool_calls'] = tool_calls
            if assistant_msg.get('content') or assistant_msg.get('tool_calls'):
                openai_messages.append(assistant_msg)

        elif role == 'user':
            text_parts = []
            tool_results: list[dict] = []

            for part in content:
                if part.get('type') == 'text':
                    text = part.get('text', '')
                    text_parts.append(text if isinstance(text, str) else json.dumps(text))
                elif part.get('type') == 'tool_result':
                    result_content = part.get('content', '')
                    tool_results.append({
                        'role': 'tool',
                        'tool_call_id': part.get('tool_use_id'),
                        'content': result_content if isinstance(result_content, str)
                        else json.dumps(result_content),
                    })

            text_content = '\n'.join(text_parts).strip()
            if text_content:
                openai_messages.append({'role': 'user', 'content': text_content})
            openai_messages.extend(tool_results)

    result: dict[str, Any] = {
        'model': model,
        'messages': system_messages + _validate_tool_calls(openai_messages),
        'stream': stream,
    }

    if temperature is not None:
        result['temperature'] = temperature

    if max_tokens is not None:
        result['max_tokens'] = max_tokens

    if top_p is not None:
        result['top_p'] = top_p

    if top_k is not None:
        result['top_k'] = top_k

    if stop_sequences:
        result['stop'] = stop_sequences

    if reasoning:
        result['reasoning'] = reasoning
    elif thinking and thinking.get('type') == 'enabled':
        result['reasoning'] = {'max_tokens': thinking.get('budget_tokens')}

    if reasoning_effort:
        result['reasoning_effort'] = reasoning_effort

    if tool_choice:
        if isinstance(tool_choice, dict):
            tc_type = tool_choice.get('type')
            if tc_type == 'auto':
                result['tool_choice'] = 'auto'
            elif tc_type == 'any':
                result['tool_choice'] = 'required'
            elif tc_type == 'tool':
                result['tool_choice'] = {
                    'type': 'function',
                    'function': {'name': tool_choice.get('name')},
                    }
        else:
            result['tool_choice'] = tool_choice

    if tools:
        result['tools'] = [
            {
                'type': 'function',
                'function': {
                    'name': t.get('name'),
                    'description': t.get('description', ''),
                    'parameters': t.get('input_schema', {}),
                },
            }
            for t in tools
        ]

    return result


def openai_to_anthropic(data: dict, model: str) -> dict:
    """Convert OpenAI API response to Anthropic format."""
    message_id = f'msg_{int(time.time() * 1000)}'
    choice = data.get('choices', [{}])[0]
    message = choice.get('message', {})

    content: list[dict] = []

    if message.get('reasoning'):
        content.append({
            'type': 'thinking',
            'thinking': message['reasoning'],
            'signature': 'openrouter-reasoning',
        })

    if message.get('content'):
        content.append({'type': 'text', 'text': message['content']})

    if message.get('tool_calls'):
        for tc in message['tool_calls']:
            func = tc.get('function', {})
            try:
                input_data = json.loads(func.get('arguments', '{}'))
            except json.JSONDecodeError:
                input_data = {}

            content.append({
                'type': 'tool_use',
                'id': tc.get('id'),
                'name': func.get('name'),
                'input': input_data,
            })

    usage = data.get('usage', {})
    finish_reason = choice.get('finish_reason', '')
    has_tool_calls = finish_reason == 'tool_calls' or message.get('tool_calls')
    stop_reason = 'tool_use' if has_tool_calls else 'end_turn'

    return {
        'id': message_id,
        'type': 'message',
        'role': 'assistant',
        'content': content,
        'model': model,
        'stop_reason': stop_reason,
        'stop_sequence': None,
        'usage': {
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
        },
    }


def count_tokens(body: dict) -> int:
    """Estimate token count from request body (~4 chars per token)."""
    char_count = 0

    system = body.get('system')
    if isinstance(system, str):
        char_count += len(system)
    elif isinstance(system, list):
        char_count += sum(len(s.get('text', '')) for s in system)

    for msg in body.get('messages', []):
        content = msg.get('content')
        if isinstance(content, str):
            char_count += len(content)
        elif isinstance(content, list):
            char_count += sum(len(p.get('text', '')) for p in content)

    return (char_count + 3) // 4  # ceil division
