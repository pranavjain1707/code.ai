import pytest
from unittest.mock import MagicMock

def test_signup_success(client, mock_supabase):
    """Test user signup endpoint."""
    mock_supabase.signup.return_value = {
        "user": MagicMock(id="user-123", email="test@example.com")
    }
    
    payload = {
        "email": "test@example.com",
        "password": "password123",
        "username": "tester"
    }
    
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert data["user_id"] == "user-123"

def test_login_success(client, mock_supabase):
    """Test user login endpoint setting cookie."""
    mock_session = MagicMock(access_token="mock_jwt_token")
    mock_supabase.login.return_value = {
        "user": MagicMock(id="user-123", email="test@example.com", user_metadata={"username": "tester"}),
        "session": mock_session
    }
    
    payload = {
        "email": "test@example.com",
        "password": "password123"
    }
    
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["access_token"] == "mock_jwt_token"
    assert "access_token" in response.cookies

def test_get_profile_requires_auth(client):
    """Test profile endpoint rejects unauthenticated requests."""
    response = client.get("/profile")
    assert response.status_code == 401
