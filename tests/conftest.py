import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Mock environment variables before importing app
import os
os.environ["DOCKER_MODEL_RUNNER_URL"] = "http://localhost:12434/v1"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "mock_anon"
os.environ["JWT_SECRET"] = "mock_jwt_secret"
os.environ["DEBUG"] = "True"

from main import app
from app.services.supabase_client import supabase_service
from app.services.local_model_client import local_model_service

@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)

@pytest.fixture(autouse=True)
def mock_cache_service(monkeypatch):
    """Automatically mock Redis cache service to avoid network dependency."""
    mock = MagicMock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.delete.return_value = True
    monkeypatch.setattr("app.services.redis_cache.cache_service", mock)
    return mock

@pytest.fixture
def mock_supabase(monkeypatch):
    """Mock Supabase client service operations."""
    mock = MagicMock()
    monkeypatch.setattr("app.api.routes.auth.supabase_service", mock)
    monkeypatch.setattr("app.api.routes.chat.supabase_service", mock)
    monkeypatch.setattr("app.api.routes.conversation.supabase_service", mock)
    monkeypatch.setattr("app.auth.jwt.supabase_service", mock)
    return mock

@pytest.fixture
def mock_local_model(monkeypatch):
    """Mock LocalModelService client operations."""
    mock = MagicMock()
    mock.get_models = AsyncMock(return_value=[
        {"id": "llama3", "name": "Llama 3 (Local)"},
        {"id": "mistral", "name": "Mistral (Local)"}
    ])
    mock.send_message = AsyncMock(return_value={
        "content": "Hello, this is a mock AI response.",
        "prompt_tokens": 10,
        "completion_tokens": 15,
        "total_tokens": 25,
        "estimated_cost": 0.0
    })
    
    # Mocking async generator stream_response
    async def mock_stream(*args, **kwargs):
        yield "data: {\"content\": \"Hello\"}\n\n"
        yield "data: {\"content\": \" world\"}\n\n"
        yield "data: {\"done\": true, \"prompt_tokens\": 10, \"completion_tokens\": 15, \"total_tokens\": 25, \"estimated_cost\": 0.0}\n\n"
        
    mock.stream_response = mock_stream
    monkeypatch.setattr("app.api.routes.chat.local_model_service", mock)
    monkeypatch.setattr("app.api.routes.conversation.local_model_service", mock)
    return mock
