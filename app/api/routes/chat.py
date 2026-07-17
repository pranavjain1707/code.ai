import time
import json
import logging
import urllib.parse
import asyncio
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from app.auth.jwt import get_current_user
from app.schemas.models import ChatRequest
from app.config.settings import settings
from app.services.supabase_client import supabase_service
from app.services.local_model_client import local_model_service
from app.services.weather_service import (
    is_weather_query, extract_city, get_weather, format_weather_for_prompt
)
from app.services.file_processor import process_uploaded_file, MAX_FILE_BYTES
from app.services.image_generator import image_generator

router = APIRouter()
logger = logging.getLogger(__name__)


def is_image_query(message: str) -> bool:
    """Detect if the user is asking to create/generate an image."""
    msg = message.lower().strip()
    # Must contain at least one image-related noun
    image_nouns = {"image", "picture", "photo", "painting", "illustration", "sketch", "drawing", "portrait", "graphic", "art", "artwork", "wallpaper"}
    # Direct patterns like "create an image of ..."
    patterns = [
        r"\b(create|generate|make|draw|paint|render|show|design)\s+(an?\s+|some\s+)?(image|picture|photo|painting|illustration|sketch|drawing|portrait|graphic|art|artwork|wallpaper)\b",
        r"\b(draw|paint|generate|create|render|design)\b.*\b(image|picture|photo|illustration|sketch|drawing|portrait|graphic|art|artwork|wallpaper)\b"
    ]
    for pattern in patterns:
        if re.search(pattern, msg):
            return True
            
    # Short forms like "draw a [something]", "paint a [something]"
    if msg.startswith(("draw ", "paint ", "generate a photo of ", "generate photo of ")):
        exclude_words = {"chart", "graph", "table", "list", "code", "function", "program", "class", "database", "query"}
        if not any(word in msg for word in exclude_words):
            return True
            
    return False


def extract_image_prompt(message: str) -> str:
    """Extract clean image prompt from user query."""
    prefix_pattern = r"^\s*(please\s+)?(create|generate|make|draw|show|paint|render)\s+(an?\s+|some\s+)?(image|picture|photo|painting|portrait|sketch|drawing|graphic|illustration)?\s*(of|about|depicting|showing)?\s*"
    cleaned = re.sub(prefix_pattern, "", message, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = "beautiful landscape"
    return cleaned



async def build_system_prompt_with_weather(message: str, base_system_prompt: Optional[str]) -> str:
    """
    If the user message is a weather query, fetch live weather data and
    prepend it to the system prompt so the LLM can answer accurately.
    Returns the (possibly enriched) system prompt string.
    """
    if not is_weather_query(message):
        return base_system_prompt or ""

    city = extract_city(message)
    if not city:
        logger.debug("Weather query detected but could not extract city name.")
        return base_system_prompt or ""

    logger.info(f"Weather query detected. Fetching weather for city: '{city}'")
    weather_data = await get_weather(city)
    if not weather_data:
        logger.warning(f"Could not fetch weather for '{city}', proceeding without weather context.")
        return base_system_prompt or ""

    weather_block = format_weather_for_prompt(weather_data)
    if base_system_prompt:
        return f"{base_system_prompt}\n\n{weather_block}"
    return weather_block

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
        
        # Fallback handling for cloud vs local models
        if settings.OPENROUTER_API_KEY:
            from app.services.local_model_client import SUPPORTED_CLOUD_MODELS
            cloud_model_ids = {m["id"] for m in SUPPORTED_CLOUD_MODELS}
            if selected_model not in cloud_model_ids:
                selected_model = "openrouter/free"
        else:
            if any(cloud_pattern in selected_model for cloud_pattern in ["google/", "openai/", "anthropic/", "meta-llama/", "mistralai/", "nvidia/"]):
                selected_model = "llama3"
                
        system_prompt = await build_system_prompt_with_weather(
            message_text, prefs.get("system_prompt")
        )
        
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
        
        # Intercept image queries
        if is_image_query(message_text):
            prompt = extract_image_prompt(message_text)
            start_time = time.time()
            image_url = await image_generator.generate_and_save_image(prompt)
            content = f"Here is the image you requested for: **{prompt}**\n\n![{prompt}]({image_url})"
            duration = time.time() - start_time
            
            # Save assistant message to database
            assistant_msg = supabase_service.create_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role="assistant",
                content=content,
                token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                response_time=duration,
                reasoning=f"Generated image for prompt: {prompt}"
            )
            
            # Log to API usage table for statistics
            supabase_service.log_api_usage(
                user_id=user_id,
                model=selected_model,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost=0.0
            )
            
            return {
                "status": "success",
                "conversation_id": conversation_id,
                "is_new_chat": is_new_chat,
                "message": assistant_msg,
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost": 0.0
                }
            }
        
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
        
        # Fallback handling for cloud vs local models
        if settings.OPENROUTER_API_KEY:
            from app.services.local_model_client import SUPPORTED_CLOUD_MODELS
            cloud_model_ids = {m["id"] for m in SUPPORTED_CLOUD_MODELS}
            if selected_model not in cloud_model_ids:
                selected_model = "openrouter/free"
        else:
            if any(cloud_pattern in selected_model for cloud_pattern in ["google/", "openai/", "anthropic/", "meta-llama/", "mistralai/", "nvidia/"]):
                selected_model = "llama3"
                
        system_prompt = await build_system_prompt_with_weather(
            message_text, prefs.get("system_prompt")
        )

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
        
        # Intercept image queries
        if is_image_query(message_text):
            async def image_event_generator():
                yield f"data: {json.dumps({'conversation_id': conversation_id, 'is_new_chat': is_new_chat})}\n\n"
                
                prompt = extract_image_prompt(message_text)
                yield f"data: {json.dumps({'reasoning': f'Analyzing request: Image generation requested.\nExtracting prompt: \"{prompt}\"\nCalling AI Image Generator...' })}\n\n"
                
                # Introduce a short delay to mimic processing / look premium
                await asyncio.sleep(0.8)
                
                start_time = time.time()
                try:
                    image_url = await image_generator.generate_and_save_image(prompt)
                    content = f"Here is the image you requested for: **{prompt}**\n\n![{prompt}]({image_url})"
                    duration = time.time() - start_time
                    
                    # Save assistant message to database
                    assistant_msg = supabase_service.create_message(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        role="assistant",
                        content=content,
                        token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                        response_time=duration,
                        reasoning=f"Generated image for prompt: {prompt}"
                    )
                    
                    # Log to API usage table for statistics
                    supabase_service.log_api_usage(
                        user_id=user_id,
                        model=selected_model,
                        prompt_tokens=0,
                        completion_tokens=0,
                        estimated_cost=0.0
                    )
                    
                    # Yield content
                    yield f"data: {json.dumps({'content': content})}\n\n"
                    
                    # Yield done event
                    yield f"data: {json.dumps({'done': True, 'message_id': assistant_msg['id'], 'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'estimated_cost': 0.0, 'response_time': duration}})}\n\n"
                except Exception as e:
                    logger.error(f"Error in image streaming generation: {e}")
                    yield f"data: {json.dumps({'error': f'Failed to generate image: {str(e)}'})}\n\n"
            
            return StreamingResponse(image_event_generator(), media_type="text/event-stream")
        
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


@router.post("/chat/upload")
async def chat_with_file(
    file: UploadFile = File(...),
    message: str = Form(default=""),
    conversation_id: Optional[str] = Form(default=None),
    model: Optional[str] = Form(default=None),
    current_user: dict = Depends(get_current_user),
):
    """
    Accepts a file upload (PDF or image) with an optional text prompt and streams
    the assistant response via SSE.

    - PDFs: extracted text is injected into the system prompt context.
    - Images: routed through the vision-capable model via multimodal message.

    The SSE event format is identical to /chat/stream so the frontend can
    reuse the same event consumer.
    """
    user_id = current_user["user"].id
    message_text = (message or "").strip()

    # --- Validate and process the uploaded file ---
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(file_bytes) / (1024*1024):.1f} MB). Maximum allowed is 10 MB.",
        )

    file_result = process_uploaded_file(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
    )

    if file_result["type"] == "error":
        raise HTTPException(status_code=400, detail=file_result["error"])

    # --- Resolve model and preferences ---
    try:
        prefs = supabase_service.get_preferences(user_id)
        selected_model = model or prefs.get("default_model") or "llama3"

        if settings.OPENROUTER_API_KEY:
            from app.services.local_model_client import SUPPORTED_CLOUD_MODELS
            cloud_model_ids = {m["id"] for m in SUPPORTED_CLOUD_MODELS}
            if selected_model not in cloud_model_ids:
                selected_model = "openrouter/free"
        else:
            if any(p in selected_model for p in ["google/", "openai/", "anthropic/", "meta-llama/", "mistralai/", "nvidia/"]):
                selected_model = "llama3"

        base_system_prompt = prefs.get("system_prompt") or ""

        # --- Resolve or create conversation ---
        conv_id = conversation_id
        is_new_chat = False
        if not conv_id:
            title_text = message_text or file_result["filename"]
            title = title_text[:40] + ("..." if len(title_text) > 40 else "")
            conv = supabase_service.create_conversation(user_id, title, selected_model)
            conv_id = conv["id"]
            is_new_chat = True

        # Save user message (include filename as context note)
        user_content = message_text or f"[File uploaded: {file_result['filename']}]"
        supabase_service.create_message(
            conversation_id=conv_id,
            user_id=user_id,
            role="user",
            content=user_content,
        )

        # Load conversation memory
        past_messages = supabase_service.get_messages(conv_id, user_id, limit=20)
        formatted_history = generate_conversation_memory(past_messages)

        # --- Build the streaming generator based on file type ---
        async def event_generator():
            yield f"data: {json.dumps({'conversation_id': conv_id, 'is_new_chat': is_new_chat})}\n\n"

            accumulated_text = ""
            start_time = time.time()

            if file_result["type"] == "pdf":
                # Inject PDF text block into system prompt
                pdf_context = file_result["pdf_text_block"]
                system_prompt = f"{base_system_prompt}\n\n{pdf_context}".strip() if base_system_prompt else pdf_context
                prompt_msg = message_text or "Please summarise this document and answer any questions about it."
                # Replace the last user message content with the user's actual question
                # The formatted history already has the user message; append question if provided
                async for chunk in local_model_service.stream_response(
                    model=selected_model,
                    messages=formatted_history,
                    system_prompt=system_prompt,
                ):
                    if chunk.startswith("data: "):
                        try:
                            d = json.loads(chunk[6:].strip())
                            if d.get("content"):
                                accumulated_text += d["content"]
                                yield chunk
                            elif d.get("error"):
                                yield chunk
                            elif d.get("done"):
                                duration = time.time() - start_time
                                p_tok = d.get("prompt_tokens", 0)
                                c_tok = d.get("completion_tokens", 0)
                                t_tok = d.get("total_tokens", 0)
                                cost = d.get("estimated_cost", 0.0)
                                assistant_msg = supabase_service.create_message(
                                    conversation_id=conv_id,
                                    user_id=user_id,
                                    role="assistant",
                                    content=accumulated_text,
                                    token_usage={"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": t_tok},
                                    response_time=duration,
                                )
                                supabase_service.log_api_usage(
                                    user_id=user_id,
                                    model=selected_model,
                                    prompt_tokens=p_tok,
                                    completion_tokens=c_tok,
                                    estimated_cost=cost,
                                )
                                yield f"data: {json.dumps({'done': True, 'message_id': assistant_msg['id'], 'usage': {'prompt_tokens': p_tok, 'completion_tokens': c_tok, 'total_tokens': t_tok, 'estimated_cost': cost, 'response_time': duration}})}\n\n"
                                return
                        except Exception:
                            pass

            elif file_result["type"] == "image":
                # Route through vision model
                image_uri = file_result["image_data_uri"]
                vision_prompt = message_text or "What do you see in this image?"
                async for chunk in local_model_service.stream_response_with_vision(
                    model=selected_model,
                    messages=formatted_history[:-1],  # exclude the placeholder user message
                    image_data_uri=image_uri,
                    user_message_text=vision_prompt,
                    system_prompt=base_system_prompt or None,
                ):
                    if chunk.startswith("data: "):
                        try:
                            d = json.loads(chunk[6:].strip())
                            if d.get("content"):
                                accumulated_text += d["content"]
                                yield chunk
                            elif d.get("done"):
                                duration = time.time() - start_time
                                p_tok = d.get("prompt_tokens", 0)
                                c_tok = d.get("completion_tokens", 0)
                                t_tok = d.get("total_tokens", 0)
                                cost = d.get("estimated_cost", 0.0)
                                assistant_msg = supabase_service.create_message(
                                    conversation_id=conv_id,
                                    user_id=user_id,
                                    role="assistant",
                                    content=accumulated_text,
                                    token_usage={"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": t_tok},
                                    response_time=duration,
                                )
                                supabase_service.log_api_usage(
                                    user_id=user_id,
                                    model=selected_model,
                                    prompt_tokens=p_tok,
                                    completion_tokens=c_tok,
                                    estimated_cost=cost,
                                )
                                yield f"data: {json.dumps({'done': True, 'message_id': assistant_msg['id'], 'usage': {'prompt_tokens': p_tok, 'completion_tokens': c_tok, 'total_tokens': t_tok, 'estimated_cost': cost, 'response_time': duration}})}\n\n"
                                return
                            elif d.get("error"):
                                yield chunk
                                return
                        except Exception:
                            yield chunk

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /chat/upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))



