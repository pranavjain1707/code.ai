from typing import Optional
from pydantic import BaseModel, EmailStr, Field

# AUTHENTICATION SCHEMAS
class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters.")
    username: str = Field(..., min_length=3, max_length=50)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ProfileUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    avatar_url: Optional[str] = None

# CHAT SCHEMAS
class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None # If None, create a new conversation thread
    message: str = Field(..., min_length=1)
    model: Optional[str] = None # Defaults to user preferences if not provided

# CONVERSATION SCHEMAS
class ConversationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    model: str

class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    is_archived: Optional[bool] = None
    is_pinned: Optional[bool] = None

# PREFERENCES SCHEMAS
class PreferencesUpdate(BaseModel):
    theme: Optional[str] = None
    default_model: Optional[str] = None
    system_prompt: Optional[str] = None
