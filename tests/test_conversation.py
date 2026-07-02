import pytest
from unittest.mock import MagicMock

@pytest.fixture
def authenticated_user(mock_supabase):
    """Set up mocked user for JWT authentication verification."""
    mock_user = MagicMock(id="user-123", email="test@example.com")
    mock_supabase.get_user_from_token.return_value = mock_user
    return mock_user

def test_list_conversations(client, mock_supabase, authenticated_user):
    """Test listing conversations."""
    mock_supabase.get_conversations.return_value = [
        {"id": "conv-1", "title": "Math Homework", "model": "google/gemini-2.5-flash", "is_pinned": False, "is_archived": False}
    ]
    
    client.cookies.set("access_token", "valid_token")
    
    response = client.get("/conversation")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["conversations"]) == 1
    assert data["conversations"][0]["title"] == "Math Homework"

def test_delete_conversation(client, mock_supabase, authenticated_user):
    """Test deleting conversation thread."""
    mock_supabase.delete_conversation.return_value = True
    
    client.cookies.set("access_token", "valid_token")
    
    response = client.delete("/conversation/conv-1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "Conversation deleted."

def test_update_conversation(client, mock_supabase, authenticated_user):
    """Test renaming/pinning conversation."""
    mock_supabase.update_conversation.return_value = {
        "id": "conv-1",
        "title": "Renamed Chat",
        "is_pinned": True
    }
    
    client.cookies.set("access_token", "valid_token")
    
    payload = {
        "title": "Renamed Chat",
        "is_pinned": True
    }
    
    response = client.put("/conversation/conv-1", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["conversation"]["title"] == "Renamed Chat"
    assert data["conversation"]["is_pinned"] is True
