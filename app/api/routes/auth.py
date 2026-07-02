import logging
from fastapi import APIRouter, Depends, HTTPException, Response, status
from app.auth.jwt import get_current_user
from app.schemas.models import UserSignup, UserLogin, ProfileUpdate, PreferencesUpdate
from app.services.supabase_client import supabase_service

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignup):
    """
    Registers a new user in Supabase Auth.
    Triggers automatically create corresponding public.profiles and public.user_preferences records.
    """
    try:
        res = supabase_service.signup(
            email=payload.email, 
            password=payload.password, 
            username=payload.username
        )
        return {
            "status": "success",
            "message": "User registered successfully. Please verify your email if required.",
            "user_id": res["user"].id
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Signup error: {error_msg}")
        if "already registered" in error_msg.lower():
            raise HTTPException(
                status_code=400, 
                detail="An account with this email address already exists."
            )
        raise HTTPException(status_code=400, detail=f"Signup failed: {error_msg}")

@router.post("/auth/login")
async def login(payload: UserLogin, response: Response):
    """
    Authenticates a user, sets a secure HTTPOnly cookie for page-rendering, and returns the JWT.
    """
    try:
        res = supabase_service.login(email=payload.email, password=payload.password)
        token = res["session"].access_token
        
        # Set access token cookie for HTML page loads
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=3600 * 24, # 24 hours
            samesite="lax",
            secure=False # Set to True in HTTPS/Production
        )
        
        return {
            "status": "success",
            "access_token": token,
            "user": {
                "id": res["user"].id,
                "email": res["user"].email,
                "user_metadata": res["user"].user_metadata
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=401, 
            detail=f"Authentication failed: {str(e)}"
        )

@router.post("/auth/logout")
async def logout(response: Response, current_user: dict = Depends(get_current_user)):
    """
    Signs out the current user session and clears authentication cookies.
    """
    try:
        supabase_service.logout(current_user["token"])
    except Exception:
        # Ignore logout errors if session was already destroyed
        pass
    
    response.delete_cookie("access_token")
    return {"status": "success", "message": "Logged out successfully."}

@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    """
    Retrieves the current user's profile and aggregated api usage analytics.
    """
    user_id = current_user["user"].id
    profile = supabase_service.get_profile(user_id)
    if not profile:
        profile = {}
        
    # Safeguard email and username from Supabase Auth user session object
    if not profile.get("email"):
        profile["email"] = getattr(current_user["user"], "email", None) or ""
    if not profile.get("username"):
        user_metadata = getattr(current_user["user"], "user_metadata", None) or {}
        profile["username"] = user_metadata.get("username") or (profile["email"].split("@")[0] if profile.get("email") else "User")
        
    usage = supabase_service.get_api_usage_stats(user_id)
    return {
        "status": "success",
        "profile": profile,
        "usage_stats": usage
    }


@router.put("/profile")
async def update_profile(payload: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    """
    Updates the current user's profile metadata.
    """
    user_id = current_user["user"].id
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided.")
        
    try:
        updated_profile = supabase_service.update_profile(user_id, updates)
        return {"status": "success", "profile": updated_profile}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    """
    Retrieves user preferences (theme, default model, system prompt).
    """
    user_id = current_user["user"].id
    prefs = supabase_service.get_preferences(user_id)
    return {"status": "success", "settings": prefs}

@router.post("/settings")
async def update_settings(payload: PreferencesUpdate, current_user: dict = Depends(get_current_user)):
    """
    Updates user preferences.
    """
    user_id = current_user["user"].id
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No preference changes provided.")
        
    try:
        updated_prefs = supabase_service.update_preferences(user_id, updates)
        return {"status": "success", "settings": updated_prefs}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
