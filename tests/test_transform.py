"""Unit tests for request/response transformations."""

import pytest
import src.models as models_module
from src.models import _build_claude_aliases, map_model
from src.transform import anthropic_to_openai, count_tokens
from src.transform import openai_to_anthropic


@pytest.fixture(autouse=True)
def mock_claude_aliases():
    """Populate Claude aliases cache for testing.
    """
    models_module._claude_aliases = {
        'haiku': 'anthropic/claude-haiku-4.5',
        'sonnet': 'anthropic/claude-sonnet-4.5',
        'opus': 'anthropic/claude-opus-4.5',
    }
    yield
    models_module._claude_aliases = None


class TestBuildClaudeAliases:
    """Tests for dynamic Claude alias extraction."""

    def test_selects_newest_by_created_timestamp(self):
        """Newest model per tier is selected based on created timestamp.
        """
        mock_data = {
            'data': [
                {'id': 'anthropic/claude-sonnet-4', 'created': 1000},
                {'id': 'anthropic/claude-sonnet-4.5', 'created': 2000},
                {'id': 'anthropic/claude-haiku-4.5', 'created': 1500},
                {'id': 'anthropic/claude-3.5-haiku', 'created': 500},
                {'id': 'anthropic/claude-opus-4.5', 'created': 3000},
            ]
        }
        aliases = _build_claude_aliases(mock_data)

        assert aliases['sonnet'] == 'anthropic/claude-sonnet-4.5'
        assert aliases['haiku'] == 'anthropic/claude-haiku-4.5'
        assert aliases['opus'] == 'anthropic/claude-opus-4.5'

    def test_excludes_free_beta_extended_variants(self):
        """Free, beta, and extended variants are excluded.
        """
        mock_data = {
            'data': [
                {'id': 'anthropic/claude-sonnet-4:free', 'created': 9999},
                {'id': 'anthropic/claude-sonnet-4:beta', 'created': 9999},
                {'id': 'anthropic/claude-sonnet-4:extended', 'created': 9999},
                {'id': 'anthropic/claude-sonnet-4', 'created': 1000},
            ]
        }
        aliases = _build_claude_aliases(mock_data)

        assert aliases['sonnet'] == 'anthropic/claude-sonnet-4'

    def test_ignores_non_anthropic_models(self):
        """Non-Anthropic models are ignored.
        """
        mock_data = {
            'data': [
                {'id': 'openai/gpt-4-sonnet', 'created': 9999},
                {'id': 'anthropic/claude-sonnet-4', 'created': 1000},
            ]
        }
        aliases = _build_claude_aliases(mock_data)

        assert aliases.get('sonnet') == 'anthropic/claude-sonnet-4'

    def test_empty_data_returns_empty_aliases(self):
        """Empty model data returns empty aliases.
        """
        aliases = _build_claude_aliases({'data': []})
        assert aliases == {}


class TestMapModel:
    """Tests for model name mapping."""

    def test_passthrough_openrouter_model(self):
        """OpenRouter model IDs pass through unchanged.
        """
        assert map_model('anthropic/claude-sonnet-4') == 'anthropic/claude-sonnet-4'
        assert map_model('google/gemini-2.5-pro') == 'google/gemini-2.5-pro'

    def test_map_haiku(self):
        """Haiku aliases map to newest haiku model.
        """
        assert map_model('claude-3-haiku') == 'anthropic/claude-haiku-4.5'
        assert map_model('claude-3-5-haiku-20241022') == 'anthropic/claude-haiku-4.5'
        assert map_model('claude-haiku-4-5-20250514') == 'anthropic/claude-haiku-4.5'

    def test_map_sonnet(self):
        """Sonnet aliases map to newest sonnet model.
        """
        assert map_model('claude-3-5-sonnet') == 'anthropic/claude-sonnet-4.5'
        assert map_model('claude-sonnet-4') == 'anthropic/claude-sonnet-4.5'
        assert map_model('claude-sonnet-4-5-20250514') == 'anthropic/claude-sonnet-4.5'

    def test_map_opus(self):
        """Opus aliases map to newest opus model.
        """
        assert map_model('claude-3-opus') == 'anthropic/claude-opus-4.5'
        assert map_model('claude-opus-4-5-20251101') == 'anthropic/claude-opus-4.5'

    def test_unknown_model_passthrough(self):
        """Unknown models pass through unchanged.
        """
        assert map_model('some-other-model') == 'some-other-model'


class TestAnthropicToOpenAI:
    """Tests for Anthropic to OpenAI request conversion."""

    def test_simple_message(self):
        """Basic message conversion with model mapping.
        """
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
        }
        result = anthropic_to_openai(body)

        assert result['model'] == 'anthropic/claude-sonnet-4.5'
        assert len(result['messages']) == 1
        assert result['messages'][0]['role'] == 'user'
        assert result['messages'][0]['content'] == 'Hello'

    def test_with_system_string(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'system': 'You are a helpful assistant.',
            'messages': [{'role': 'user', 'content': 'Hello'}],
        }
        result = anthropic_to_openai(body)

        assert len(result['messages']) == 2
        assert result['messages'][0]['role'] == 'system'
        assert result['messages'][0]['content'][0]['text'] == 'You are a helpful assistant.'

    def test_with_system_list(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'system': [{'text': 'System prompt 1'}, {'text': 'System prompt 2'}],
            'messages': [{'role': 'user', 'content': 'Hello'}],
        }
        result = anthropic_to_openai(body)

        assert len(result['messages']) == 3
        assert result['messages'][0]['content'][0]['text'] == 'System prompt 1'
        assert result['messages'][1]['content'][0]['text'] == 'System prompt 2'

    def test_model_override(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
        }
        result = anthropic_to_openai(body, model_override='x-ai/grok-4')

        assert result['model'] == 'x-ai/grok-4'

    def test_tool_use_message(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [
                {'role': 'user', 'content': "What's the weather?"},
                {
                    'role': 'assistant',
                    'content': [
                        {'type': 'text', 'text': 'Let me check.'},
                        {
                            'type': 'tool_use',
                            'id': 'tool_123',
                            'name': 'get_weather',
                            'input': {'location': 'NYC'},
                        },
                    ],
                },
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'tool_123',
                            'content': 'Sunny, 72F',
                        }
                    ],
                },
            ],
        }
        result = anthropic_to_openai(body)

        # Check assistant message has tool_calls
        assistant_msg = result['messages'][1]
        assert assistant_msg['role'] == 'assistant'
        assert assistant_msg['content'] == 'Let me check.'
        assert len(assistant_msg['tool_calls']) == 1
        assert assistant_msg['tool_calls'][0]['id'] == 'tool_123'
        assert assistant_msg['tool_calls'][0]['function']['name'] == 'get_weather'

        # Check tool result message
        tool_msg = result['messages'][2]
        assert tool_msg['role'] == 'tool'
        assert tool_msg['tool_call_id'] == 'tool_123'
        assert tool_msg['content'] == 'Sunny, 72F'

    def test_tools_conversion(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'tools': [
                {
                    'name': 'get_weather',
                    'description': 'Get current weather',
                    'input_schema': {
                        'type': 'object',
                        'properties': {'location': {'type': 'string'}},
                    },
                }
            ],
        }
        result = anthropic_to_openai(body)

        assert len(result['tools']) == 1
        assert result['tools'][0]['type'] == 'function'
        assert result['tools'][0]['function']['name'] == 'get_weather'
        assert result['tools'][0]['function']['description'] == 'Get current weather'

    def test_stream_flag(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'stream': True,
        }
        result = anthropic_to_openai(body)

        assert result['stream'] is True

    def test_temperature(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'temperature': 0.7,
        }
        result = anthropic_to_openai(body)

        assert result['temperature'] == 0.7

    def test_reasoning_passthrough(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'reasoning': {'effort': 'medium'},
        }
        result = anthropic_to_openai(body)

        assert result['reasoning'] == {'effort': 'medium'}

    def test_thinking_to_reasoning(self):
        body = {
            'model': 'claude-3-5-sonnet',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'thinking': {'type': 'enabled', 'budget_tokens': 5000},
        }
        result = anthropic_to_openai(body)

        assert result['reasoning'] == {'max_tokens': 5000}


class TestOpenAIToAnthropic:
    """Tests for OpenAI to Anthropic response conversion."""

    def test_simple_response(self):
        data = {
            'id': 'chatcmpl-123',
            'choices': [{'message': {'content': 'Hello there!'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        }
        result = openai_to_anthropic(data, 'anthropic/claude-sonnet-4')

        assert result['type'] == 'message'
        assert result['role'] == 'assistant'
        assert result['model'] == 'anthropic/claude-sonnet-4'
        assert result['stop_reason'] == 'end_turn'
        assert len(result['content']) == 1
        assert result['content'][0]['type'] == 'text'
        assert result['content'][0]['text'] == 'Hello there!'
        assert result['usage']['input_tokens'] == 10
        assert result['usage']['output_tokens'] == 5

    def test_tool_call_response(self):
        data = {
            'id': 'chatcmpl-123',
            'choices': [
                {
                    'message': {
                        'tool_calls': [
                            {
                                'id': 'call_123',
                                'function': {
                                    'name': 'get_weather',
                                    'arguments': '{"location": "NYC"}',
                                },
                            }
                        ]
                    }
                }
            ],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        }
        result = openai_to_anthropic(data, 'anthropic/claude-sonnet-4')

        assert result['stop_reason'] == 'tool_use'
        assert len(result['content']) == 1
        assert result['content'][0]['type'] == 'tool_use'
        assert result['content'][0]['id'] == 'call_123'
        assert result['content'][0]['name'] == 'get_weather'
        assert result['content'][0]['input'] == {'location': 'NYC'}

    def test_reasoning_response(self):
        data = {
            'id': 'chatcmpl-123',
            'choices': [
                {
                    'message': {
                        'reasoning': 'Let me think about this...',
                        'content': 'The answer is 42.',
                    }
                }
            ],
            'usage': {},
        }
        result = openai_to_anthropic(data, 'anthropic/claude-sonnet-4')

        assert len(result['content']) == 2
        assert result['content'][0]['type'] == 'thinking'
        assert result['content'][0]['thinking'] == 'Let me think about this...'
        assert result['content'][1]['type'] == 'text'
        assert result['content'][1]['text'] == 'The answer is 42.'


class TestCountTokens:
    """Tests for token counting."""

    def test_simple_message(self):
        body = {'messages': [{'content': 'Hello world'}]}  # 11 chars
        assert count_tokens(body) == 3  # ceil(11/4) = 3

    def test_with_system(self):
        body = {
            'system': 'You are helpful.',  # 16 chars
            'messages': [{'content': 'Hi'}],  # 2 chars
        }
        assert count_tokens(body) == 5  # ceil(18/4) = 5

    def test_with_system_list(self):
        body = {
            'system': [{'text': 'Hello'}, {'text': 'World'}],  # 10 chars
            'messages': [],
        }
        assert count_tokens(body) == 3  # ceil(10/4) = 3

    def test_complex_content(self):
        body = {
            'messages': [
                {'content': [{'text': 'Hello'}, {'text': 'World'}]}  # 10 chars
            ]
        }
        assert count_tokens(body) == 3
