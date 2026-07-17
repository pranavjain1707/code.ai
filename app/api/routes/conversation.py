from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from app.auth.jwt import get_current_user
from app.schemas.models import ConversationCreate, ConversationUpdate
from app.services.supabase_client import supabase_service
from app.services.local_model_client import local_model_service

router = APIRouter()

@router.post("/conversation", status_code=status.HTTP_201_CREATED)
async def create_conversation(payload: ConversationCreate, current_user: dict = Depends(get_current_user)):
    """
    Creates a new conversation thread.
    """
    user_id = current_user["user"].id
    try:
        conv = supabase_service.create_conversation(user_id, payload.title, payload.model)
        return {"status": "success", "conversation": conv}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/conversation")
async def list_conversations(include_archived: bool = False, current_user: dict = Depends(get_current_user)):
    """
    Lists conversations for the current user.
    """
    user_id = current_user["user"].id
    try:
        convs = supabase_service.get_conversations(user_id, include_archived=include_archived)
        return {"status": "success", "conversations": convs}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/conversation/{conversation_id}")
async def get_conversation_details(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """
    Gets details of a conversation and its messages.
    """
    user_id = current_user["user"].id
    conv = supabase_service.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    
    messages = supabase_service.get_messages(conversation_id, user_id)
    return {
        "status": "success",
        "conversation": conv,
        "messages": messages
    }

@router.put("/conversation/{conversation_id}")
async def update_conversation_details(
    conversation_id: str, 
    payload: ConversationUpdate, 
    current_user: dict = Depends(get_current_user)
):
    """
    Updates conversation properties (e.g. rename, pin, archive).
    """
    user_id = current_user["user"].id
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided.")
        
    try:
        updated = supabase_service.update_conversation(conversation_id, user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Conversation not found or unauthorized.")
        return {"status": "success", "conversation": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/conversation/{conversation_id}")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """
    Deletes a conversation.
    """
    user_id = current_user["user"].id
    success = supabase_service.delete_conversation(conversation_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized.")
    return {"status": "success", "message": "Conversation deleted."}

@router.post("/conversation/favorite")
async def toggle_favorite_message(message_id: str, current_user: dict = Depends(get_current_user)):
    """
    Toggles a message as favorited or unfavorited.
    """
    user_id = current_user["user"].id
    try:
        res = supabase_service.toggle_favorite(user_id, message_id)
        return {"status": "success", "data": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/history")
async def get_chat_history_or_search(q: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """
    Search past conversations.
    If 'q' is provided, performs a text search on conversation titles and message content.
    Otherwise, returns all active conversations.
    """
    user_id = current_user["user"].id
    if not q:
        convs = supabase_service.get_conversations(user_id, include_archived=True)
        return {"status": "success", "conversations": convs}
    
    # Perform search
    try:
        # Search matching conversations by title
        title_matches = supabase_service.admin_client.table("conversations")\
            .select("*")\
            .eq("user_id", user_id)\
            .ilike("title", f"%{q}%")\
            .execute()
        
        # Search messages containing content
        message_matches = supabase_service.admin_client.table("messages")\
            .select("conversation_id, content")\
            .eq("user_id", user_id)\
            .ilike("content", f"%{q}%")\
            .execute()
            
        # Compile unique conversations
        conv_ids = {c["id"] for c in title_matches.data}
        for msg in message_matches.data:
            conv_ids.add(msg["conversation_id"])
            
        if not conv_ids:
            return {"status": "success", "conversations": []}
            
        # Get details of those conversations
        results = supabase_service.admin_client.table("conversations")\
            .select("*")\
            .in_("id", list(conv_ids))\
            .order("updated_at", desc=True)\
            .execute()
            
        return {"status": "success", "conversations": results.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.get("/models")
async def get_models():
    """
    Lists all available models retrieved from local runner (cached).
    """
    try:
        models = await local_model_service.get_models()
        return {"status": "success", "models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
