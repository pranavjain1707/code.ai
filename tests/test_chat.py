import pytest
from unittest.mock import MagicMock

@pytest.fixture
def authenticated_user(mock_supabase):
    """Set up mocked user for JWT authentication verification."""
    mock_user = MagicMock(id="user-123", email="test@example.com")
    mock_supabase.get_user_from_token.return_value = mock_user
    mock_supabase.get_preferences.return_value = {
        "theme": "dark",
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
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
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free"
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
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free"
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


from app.api.routes.chat import is_image_query, extract_image_prompt
from unittest.mock import AsyncMock

def test_image_query_detection_and_extraction():
    """Test helper functions that detect image queries and extract prompts."""
    # Positive cases
    assert is_image_query("generate an image of a blue butterfly") is True
    assert is_image_query("draw a cute dog playing fetch") is True
    assert is_image_query("create photo of a sunset over the ocean") is True
    assert is_image_query("paint a forest in autumn style") is True

    # Negative cases
    assert is_image_query("how to draw a flow chart in python") is False
    assert is_image_query("explain how to paint database queries") is False
    assert is_image_query("hello bot") is False

    # Extraction cases
    assert extract_image_prompt("generate an image of a blue butterfly") == "a blue butterfly"
    assert extract_image_prompt("draw a cute dog playing fetch") == "cute dog playing fetch"
    assert extract_image_prompt("create photo of a sunset over the ocean") == "a sunset over the ocean"
    assert extract_image_prompt("paint a forest in autumn style") == "forest in autumn style"



@pytest.mark.asyncio
async def test_chat_blocking_image_generation(client, mock_supabase, monkeypatch):
    """Test image generation through blocking chat route."""
    # Mock image_generator
    mock_gen = AsyncMock(return_value="/static/generated/mock-image.png")
    monkeypatch.setattr("app.api.routes.chat.image_generator.generate_and_save_image", mock_gen)

    mock_supabase.create_conversation.return_value = {"id": "conv-img-123"}
    mock_supabase.create_message.return_value = {
        "id": "msg-img-123",
        "role": "assistant",
        "content": "Here is the image you requested for: **a flying saucer**\n\n![a flying saucer](/static/generated/mock-image.png)"
    }
    mock_supabase.get_messages.return_value = []
    
    payload = {
        "message": "create an image of a flying saucer",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free"
    }
    
    client.cookies.set("access_token", "valid_token")
    response = client.post("/chat", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["conversation_id"] == "conv-img-123"
    assert "![a flying saucer](/static/generated/mock-image.png)" in data["message"]["content"]
    
    mock_gen.assert_called_once_with("a flying saucer")
    assert mock_supabase.create_message.called


@pytest.mark.asyncio
async def test_chat_streaming_image_generation(client, mock_supabase, monkeypatch):
    """Test image generation through streaming chat route."""
    # Mock image_generator
    mock_gen = AsyncMock(return_value="/static/generated/mock-image.png")
    monkeypatch.setattr("app.api.routes.chat.image_generator.generate_and_save_image", mock_gen)

    mock_supabase.create_conversation.return_value = {"id": "conv-img-456"}
    mock_supabase.create_message.return_value = {
        "id": "msg-img-456",
        "role": "assistant",
        "content": "Here is the image you requested for: **a flying saucer**\n\n![a flying saucer](/static/generated/mock-image.png)"
    }
    mock_supabase.get_messages.return_value = []
    
    payload = {
        "message": "create an image of a flying saucer",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free"
    }
    
    client.cookies.set("access_token", "valid_token")
    response = client.post("/chat/stream", json=payload)
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    content = response.text
    assert "conv-img-456" in content
    assert "Analyzing request: Image generation requested" in content
    assert "![a flying saucer](/static/generated/mock-image.png)" in content
    assert '"done": true' in content
    
    mock_gen.assert_called_once_with("a flying saucer")


