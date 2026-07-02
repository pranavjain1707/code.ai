import time
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.auth.jwt import get_current_user
from app.schemas.models import ChatRequest
from app.services.supabase_client import supabase_service
from app.services.local_model_client import local_model_service

router = APIRouter()
logger = logging.getLogger(__name__)

def generate_conversation_memory(messages: list) -> list:
    """Format Supabase messages into OpenRouter compatible chat history."""
    formatted = []
    for msg in messages:
        item = {
            "role": msg["role"],
            "content": msg["content"]
        }
        if msg["role"] == "assistant" and msg.get("reasoning"):
            item["reasoning_details"] = msg["reasoning"]
        formatted.append(item)
    return formatted

@router.post("/chat")
async def chat_blocking(payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Sends prompt to OpenRouter and waits for the full response.
    Saves both the user query and assistant response to Supabase.
    """
    user_id = current_user["user"].id
    message_text = payload.message.strip()
    
    if not message_text:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
        
    try:
        # Retrieve user preferences
        prefs = supabase_service.get_preferences(user_id)
        selected_model = payload.model or prefs.get("default_model") or "llama3"
        # Fallback legacy cloud models to local default model
        if any(cloud_pattern in selected_model for cloud_pattern in ["google/", "openai/", "anthropic/", "meta-llama/", "mistralai/"]):
            selected_model = "llama3"
        system_prompt = prefs.get("system_prompt")
        
        conversation_id = payload.conversation_id
        is_new_chat = False
        
        # Create conversation if id not provided
        if not conversation_id:
            title = message_text[:40] + ("..." if len(message_text) > 40 else "")
            conv = supabase_service.create_conversation(user_id, title, selected_model)
            conversation_id = conv["id"]
            is_new_chat = True
            
        # Save user message to database
        supabase_service.create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=message_text
        )
        
        # Load conversation memory (last 20 messages for context)
        past_messages = supabase_service.get_messages(conversation_id, user_id, limit=20)
        formatted_history = generate_conversation_memory(past_messages)
        
        # Send to OpenRouter and time the response
        start_time = time.time()
        response_data = await local_model_service.send_message(
            model=selected_model,
            messages=formatted_history,
            system_prompt=system_prompt
        )
        duration = time.time() - start_time
        
        # Save assistant message to database
        assistant_msg = supabase_service.create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=response_data["content"],
            token_usage={
                "prompt_tokens": response_data["prompt_tokens"],
                "completion_tokens": response_data["completion_tokens"],
                "total_tokens": response_data["total_tokens"]
            },
            response_time=duration,
            reasoning=response_data.get("reasoning")
        )
        
        # Log to API usage table for statistics
        supabase_service.log_api_usage(
            user_id=user_id,
            model=selected_model,
            prompt_tokens=response_data["prompt_tokens"],
            completion_tokens=response_data["completion_tokens"],
            estimated_cost=response_data["estimated_cost"]
        )
        
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "is_new_chat": is_new_chat,
            "message": assistant_msg,
            "usage": {
                "prompt_tokens": response_data["prompt_tokens"],
                "completion_tokens": response_data["completion_tokens"],
                "total_tokens": response_data["total_tokens"],
                "estimated_cost": response_data["estimated_cost"]
            }
        }
    except Exception as e:
        logger.error(f"Error in blocking chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/stream")
async def chat_streaming(payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Streams the assistant response in real-time.
    Saves user prompt immediately, streams AI tokens, and saves final response at stream completion.
    """
    user_id = current_user["user"].id
    message_text = payload.message.strip()
    
    if not message_text:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
        
    try:
        prefs = supabase_service.get_preferences(user_id)
        selected_model = payload.model or prefs.get("default_model") or "llama3"
        # Fallback legacy cloud models to local default model
        if any(cloud_pattern in selected_model for cloud_pattern in ["google/", "openai/", "anthropic/", "meta-llama/", "mistralai/"]):
            selected_model = "llama3"
        system_prompt = prefs.get("system_prompt")
        
        conversation_id = payload.conversation_id
        is_new_chat = False
        
        if not conversation_id:
            title = message_text[:40] + ("..." if len(message_text) > 40 else "")
            conv = supabase_service.create_conversation(user_id, title, selected_model)
            conversation_id = conv["id"]
            is_new_chat = True
            
        # Save user message immediately
        supabase_service.create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=message_text
        )
        
        # Load memory
        past_messages = supabase_service.get_messages(conversation_id, user_id, limit=20)
        formatted_history = generate_conversation_memory(past_messages)
        
        async def event_generator():
            # First event tells the frontend what conversation ID we are working with
            yield f"data: {json.dumps({'conversation_id': conversation_id, 'is_new_chat': is_new_chat})}\n\n"
            
            accumulated_text = ""
            start_time = time.time()
            
            async for chunk in local_model_service.stream_response(
                model=selected_model,
                messages=formatted_history,
                system_prompt=system_prompt
            ):
                if not chunk.startswith("data: "):
                    continue
                    
                data_str = chunk[6:].strip()
                if not data_str:
                    continue
                
                try:
                    data_json = json.loads(data_str)
                    
                    # If this is the ending token usage block
                    if data_json.get("done") is True:
                        duration = time.time() - start_time
                        p_tok = data_json.get("prompt_tokens", 0)
                        c_tok = data_json.get("completion_tokens", 0)
                        t_tok = data_json.get("total_tokens", 0)
                        cost = data_json.get("estimated_cost", 0.0)
                        
                        # Save completed assistant response to DB
                        assistant_msg = supabase_service.create_message(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            role="assistant",
                            content=accumulated_text,
                            token_usage={
                                "prompt_tokens": p_tok,
                                "completion_tokens": c_tok,
                                "total_tokens": t_tok
                            },
                            response_time=duration,
                            reasoning=data_json.get("reasoning")
                        )
                        
                        # Log API usage
                        supabase_service.log_api_usage(
                            user_id=user_id,
                            model=selected_model,
                            prompt_tokens=p_tok,
                            completion_tokens=c_tok,
                            estimated_cost=cost
                        )
                        
                        # Forward final saved message details and usage stats
                        yield f"data: {json.dumps({'done': True, 'message_id': assistant_msg['id'], 'usage': {'prompt_tokens': p_tok, 'completion_tokens': c_tok, 'total_tokens': t_tok, 'estimated_cost': cost, 'response_time': duration}})}\n\n"
                    else:
                        # Append content chunk and yield to client
                        content_chunk = data_json.get("content", "")
                        accumulated_text += content_chunk
                        yield chunk
                except Exception as e:
                    logger.error(f"Error parsing streaming chunk: {e}")
                    yield chunk

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except Exception as e:
        logger.error(f"Error setting up streaming chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))
