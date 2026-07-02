import logging
from fastapi import Request, HTTPException
from app.services.supabase_client import supabase_service

logger = logging.getLogger(__name__)

async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency to retrieve the currently logged-in user.
    Extracts the Supabase JWT token from either the Authorization header or the access_token cookie.
    """
    token = None
    
    # Check Authorization Header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        
    # Fallback to Cookie (useful for pages and standard browser requests)
    if not token:
        token = request.cookies.get("access_token")
        
    if not token:
        raise HTTPException(
            status_code=401, 
            detail="Authentication credentials were not provided."
        )
        
    user = supabase_service.get_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired session. Please log in again."
        )
        
    return {
        "user": user,
        "token": token
    }
