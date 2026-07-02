import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.local_model_client import local_model_service, LocalModelService

@pytest.mark.asyncio
async def test_local_model_blocking():
    """Verify that send_message routes requests to the local model runner and sets cost to 0.0."""
    service = LocalModelService()
    
    # Create mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Hello from local model!",
                "reasoning_content": "Thinking process"
            }
        }],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8
        }
    }
    
    with patch.object(service, '_send_request_with_retry', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        
        result = await service.send_message(
            model="llama3",
            messages=[{"role": "user", "content": "hi"}]
        )
        
        # Verify that _send_request_with_retry was called
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        
        payload = args[0]
        assert payload["model"] == "llama3"
        assert payload["messages"][-1]["content"] == "hi"
        
        # Verify result contains the expected content, reasoning and cost
        assert result["content"] == "Hello from local model!"
        assert result["reasoning"] == "Thinking process"
        assert result["estimated_cost"] == 0.0

@pytest.mark.asyncio
async def test_local_model_streaming():
    """Verify that stream_response streams from the local runner and handles done/cost parameters."""
    service = LocalModelService()
    
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    
    async def mock_iter_lines():
        yield 'data: {"choices": [{"delta": {"reasoning_content": "Thinking..."}}]}'
        yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
        yield 'data: [DONE]'
        
    mock_response.aiter_lines = mock_iter_lines
    
    with patch.object(service, '_send_request_with_retry', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        
        chunks = []
        async for chunk in service.stream_response(
            model="llama3",
            messages=[{"role": "user", "content": "hi"}]
        ):
            chunks.append(chunk)
            
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        
        payload = args[0]
        assert payload["model"] == "llama3"
        assert payload["stream"] is True
        
        # Check parsed chunks
        assert len(chunks) == 3
        assert "Thinking..." in chunks[0]
        assert "Hello" in chunks[1]
        assert '"done": true' in chunks[2]
        assert '"estimated_cost": 0.0' in chunks[2]
