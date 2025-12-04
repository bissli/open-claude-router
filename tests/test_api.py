"""Integration tests for API endpoints."""

import json
from unittest.mock import AsyncMock, patch

import pytest
import src.models as models_module
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock
from src.main import app


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


class TestStartupLifespan:
    """Tests for application startup behavior."""

    def test_fetch_models_called_on_startup(self):
        """Verify fetch_models is called during app lifespan startup."""
        with patch.object(
            models_module, 'fetch_models', new_callable=AsyncMock
        ) as mock_fetch:
            with TestClient(app):
                pass
            mock_fetch.assert_called_once()

    def test_aliases_populated_after_startup(self, httpx_mock: HTTPXMock):
        """Verify Claude aliases are available after startup."""
        # Clear the cache to simulate fresh startup
        models_module._claude_aliases = None
        models_module._cached_models = None

        # Mock the OpenRouter API response
        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/models',
            json={
                'data': [
                    {'id': 'anthropic/claude-opus-4.5', 'created': 1700000003},
                    {'id': 'anthropic/claude-sonnet-4.5', 'created': 1700000002},
                    {'id': 'anthropic/claude-haiku-4.5', 'created': 1700000001},
                ]
            },
        )

        # Remove the autouse fixture's mock for this test
        with patch.object(
            models_module, '_claude_aliases', None
        ), patch.object(
            models_module, '_cached_models', None
        ):
            with TestClient(app):
                aliases = models_module.get_claude_aliases()
                assert 'opus' in aliases
                assert 'sonnet' in aliases
                assert 'haiku' in aliases
                assert aliases['opus'] == 'anthropic/claude-opus-4.5'


@pytest.fixture
def client():
    """Create test client.
    """
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_root_returns_ok(self, client):
        response = client.get('/')
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert data['service'] == 'open-claude-router'


class TestCountTokensEndpoint:
    """Tests for the token counting endpoint."""

    def test_count_tokens_simple(self, client):
        response = client.post(
            '/v1/messages/count_tokens',
            json={'messages': [{'content': 'Hello world!'}]},  # 12 chars
        )
        assert response.status_code == 200
        data = response.json()
        assert data['input_tokens'] == 3  # ceil(12/4)

    def test_count_tokens_with_system(self, client):
        response = client.post(
            '/v1/messages/count_tokens',
            json={
                'system': 'Be helpful.',  # 11 chars
                'messages': [{'content': 'Hi'}],  # 2 chars
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data['input_tokens'] == 4  # ceil(13/4)


class TestMessagesEndpoint:
    """Tests for the /v1/messages endpoint."""

    def test_missing_api_key(self, client):
        with patch('src.main.config') as mock_config:
            mock_config.openrouter_api_key = None
            mock_config.model_override = None
            response = client.post(
                '/v1/messages',
                json={
                    'model': 'claude-3-5-sonnet',
                    'messages': [{'role': 'user', 'content': 'Hello'}],
                },
            )
        assert response.status_code == 401
        assert 'API key required' in response.json()['error']['message']

    def test_successful_request(self, client, httpx_mock: HTTPXMock):
        # Mock OpenRouter response
        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/chat/completions',
            json={
                'id': 'chatcmpl-123',
                'choices': [{'message': {'content': 'Hello! How can I help?'}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 8},
            },
        )

        response = client.post(
            '/v1/messages',
            headers={'X-Api-Key': 'test-key'},
            json={
                'model': 'claude-3-5-sonnet',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data['type'] == 'message'
        assert data['role'] == 'assistant'
        assert data['content'][0]['type'] == 'text'
        assert data['content'][0]['text'] == 'Hello! How can I help?'
        assert data['usage']['input_tokens'] == 10
        assert data['usage']['output_tokens'] == 8

    def test_authorization_header(self, client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/chat/completions',
            json={
                'id': 'chatcmpl-123',
                'choices': [{'message': {'content': 'Hi!'}}],
                'usage': {},
            },
        )

        response = client.post(
            '/v1/messages',
            headers={'Authorization': 'Bearer test-key'},
            json={
                'model': 'claude-3-5-sonnet',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

        assert response.status_code == 200

    def test_tool_call_response(self, client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/chat/completions',
            json={
                'id': 'chatcmpl-123',
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'call_abc123',
                                    'function': {
                                        'name': 'get_weather',
                                        'arguments': '{"location": "NYC"}',
                                    },
                                }
                            ]
                        }
                    }
                ],
                'usage': {'prompt_tokens': 15, 'completion_tokens': 20},
            },
        )

        response = client.post(
            '/v1/messages',
            headers={'X-Api-Key': 'test-key'},
            json={
                'model': 'claude-3-5-sonnet',
                'messages': [{'role': 'user', 'content': "What's the weather?"}],
                'tools': [
                    {
                        'name': 'get_weather',
                        'description': 'Get weather',
                        'input_schema': {'type': 'object'},
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data['stop_reason'] == 'tool_use'
        assert data['content'][0]['type'] == 'tool_use'
        assert data['content'][0]['name'] == 'get_weather'
        assert data['content'][0]['input'] == {'location': 'NYC'}

    def test_upstream_error(self, client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/chat/completions',
            status_code=429,
            text='Rate limit exceeded',
        )

        response = client.post(
            '/v1/messages',
            headers={'X-Api-Key': 'test-key'},
            json={
                'model': 'claude-3-5-sonnet',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

        assert response.status_code == 429

    def test_model_mapping(self, client, httpx_mock: HTTPXMock):
        """Verify model names are correctly mapped to newest versions.
        """
        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/chat/completions',
            json={
                'id': 'chatcmpl-123',
                'choices': [{'message': {'content': 'Hi'}}],
                'usage': {},
            },
        )

        client.post(
            '/v1/messages',
            headers={'X-Api-Key': 'test-key'},
            json={
                'model': 'claude-3-5-sonnet-20241022',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

        request = httpx_mock.get_requests()[0]
        body = json.loads(request.content)
        assert body['model'] == 'anthropic/claude-sonnet-4.5'


class TestStreamingEndpoint:
    """Tests for streaming responses."""

    def test_streaming_request_format(self, client, httpx_mock: HTTPXMock):
        """Test that streaming requests are properly formatted."""
        # Mock a simple streaming response
        sse_response = (
            'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
            'data: {"usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\n'
            'data: [DONE]\n\n'
        )

        httpx_mock.add_response(
            url='https://openrouter.ai/api/v1/chat/completions',
            text=sse_response,
            headers={'content-type': 'text/event-stream'},
        )

        response = client.post(
            '/v1/messages',
            headers={'X-Api-Key': 'test-key'},
            json={
                'model': 'claude-3-5-sonnet',
                'messages': [{'role': 'user', 'content': 'Hello'}],
                'stream': True,
            },
        )

        assert response.status_code == 200
        assert 'text/event-stream' in response.headers.get('content-type', '')

        # Parse SSE events
        content = response.text
        assert 'event: message_start' in content
        assert 'event: message_stop' in content
