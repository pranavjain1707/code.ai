import pytest
from unittest.mock import MagicMock

@pytest.fixture
def authenticated_user(mock_supabase):
    """Set up mocked user for JWT authentication verification."""
    mock_user = MagicMock(id="user-123", email="test@example.com")
    mock_supabase.get_user_from_token.return_value = mock_user
    mock_supabase.get_preferences.return_value = {
        "theme": "dark",
        "default_model": "google/gemini-2.5-flash",
        "system_prompt": "You are a helpful assistant."
    }
    return mock_user

def test_chat_blocking(client, mock_supabase, mock_local_model, authenticated_user):
    """Test blocking chat completion endpoint."""
    mock_supabase.create_conversation.return_value = {"id": "conv-123"}
    mock_supabase.create_message.return_value = {
        "id": "msg-123",
        "role": "assistant",
        "content": "Hello, this is a mock AI response."
    }
    mock_supabase.get_messages.return_value = []
    
    payload = {
        "message": "Explain recursion in Python",
        "model": "google/gemini-2.5-flash"
    }
    
    # Set access token cookie to pass auth check
    client.cookies.set("access_token", "valid_token")
    
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["conversation_id"] == "conv-123"
    assert data["message"]["content"] == "Hello, this is a mock AI response."
    assert mock_supabase.create_message.called

def test_chat_streaming(client, mock_supabase, mock_local_model, authenticated_user):
    """Test SSE streaming chat completion endpoint."""
    mock_supabase.create_conversation.return_value = {"id": "conv-123"}
    mock_supabase.get_messages.return_value = []
    mock_supabase.create_message.return_value = {
        "id": "msg-123",
        "role": "assistant",
        "content": "Hello world"
    }
    
    payload = {
        "message": "Explain recursion in Python",
        "model": "google/gemini-2.5-flash"
    }
    
    client.cookies.set("access_token", "valid_token")
    
    # Read streamed response lines
    response = client.post("/chat/stream", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    content = response.text
    assert "conv-123" in content
    assert "Hello" in content
    assert "world" in content
    assert '"done": true' in content

def test_chat_model_fallback_cloud(client, mock_supabase, mock_local_model, authenticated_user, monkeypatch):
    """Test that requests with invalid/local model ID fallback to a cloud model when OpenRouter is active."""
    from app.config.settings import settings
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-v1-mock-key")
    
    mock_supabase.create_conversation.return_value = {"id": "conv-fallback"}
    mock_supabase.create_message.return_value = {
        "id": "msg-fallback",
        "role": "assistant",
        "content": "Cloud response"
    }
    mock_supabase.get_messages.return_value = []
    
    payload = {
        "message": "Hello",
        "model": "llama3:latest" # Legacy local model name
    }
    
    client.cookies.set("access_token", "valid_token")
    
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    
    # Verify that the model passed to local_model_service.send_message was "openrouter/free"
    # instead of "llama3:latest"
    mock_local_model.send_message.assert_called_once()
    called_kwargs = mock_local_model.send_message.call_args[1]
    assert called_kwargs["model"] == "openrouter/free"

