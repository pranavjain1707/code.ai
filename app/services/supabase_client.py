import logging
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
from app.config.settings import settings

logger = logging.getLogger(__name__)

class SupabaseService:
    def __init__(self):
        if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
            logger.error("Supabase URL or Anon Key is missing from settings!")
            self.client = None
            self.admin_client = None
            return

        self.client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
        
        # Admin client bypasses RLS, useful for system operations or safe backend filtering
        service_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY
        self.admin_client: Client = create_client(settings.SUPABASE_URL, service_key)
        logger.info("Supabase client initialized successfully.")

    # AUTHENTICATION
    def signup(self, email: str, password: str, username: str) -> Dict[str, Any]:
        """Sign up a new user with email and password."""
        if not self.client:
            raise Exception("Supabase client not initialized")
        
        # Pass username in options metadata
        response = self.client.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "username": username
                }
            }
        })
        return {
            "user": response.user,
            "session": response.session
        }

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Log in an existing user."""
        if not self.client:
            raise Exception("Supabase client not initialized")
        
        response = self.client.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        return {
            "user": response.user,
            "session": response.session
        }

    def logout(self, token: str) -> None:
        """Sign out a user session."""
        if not self.client:
            raise Exception("Supabase client not initialized")
        
        # To sign out, we set the auth token on the client first
        self.client.postgrest.auth(token)
        self.client.auth.sign_out()

    def get_user_from_token(self, token: str) -> Optional[Any]:
        """Validate JWT token and return Supabase user object."""
        if not self.client:
            return None
        try:
            # We can retrieve user details by calling get_user with the JWT token
            response = self.client.auth.get_user(token)
            return response.user
        except Exception as e:
            logger.error(f"Failed to get user from token: {e}")
            return None

    # CONVERSATIONS CRUD
    def get_conversations(self, user_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
        """Get conversations for a specific user, sorted by updated_at."""
        if not self.admin_client:
            return []
        query = self.admin_client.table("conversations").select("*").eq("user_id", user_id)
        if not include_archived:
            query = query.eq("is_archived", False)
        
        # Sort pinned conversations first, then by updated_at desc
        response = query.order("is_pinned", desc=True).order("updated_at", desc=True).execute()
        return response.data

    def get_conversation(self, conversation_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific conversation."""
        if not self.admin_client:
            return None
        response = self.admin_client.table("conversations").select("*")\
            .eq("id", conversation_id).eq("user_id", user_id).execute()
        return response.data[0] if response.data else None

    def create_conversation(self, user_id: str, title: str, model: str) -> Dict[str, Any]:
        """Create a new conversation thread."""
        if not self.admin_client:
            raise Exception("Supabase client not initialized")
        response = self.admin_client.table("conversations").insert({
            "user_id": user_id,
            "title": title,
            "model": model
        }).execute()
        return response.data[0]

    def update_conversation(self, conversation_id: str, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update properties of a conversation (title, is_archived, is_pinned)."""
        if not self.admin_client:
            return None
        updates["updated_at"] = "now()"
        response = self.admin_client.table("conversations").update(updates)\
            .eq("id", conversation_id).eq("user_id", user_id).execute()
        return response.data[0] if response.data else None

    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """Delete a conversation."""
        if not self.admin_client:
            return False
        response = self.admin_client.table("conversations").delete()\
            .eq("id", conversation_id).eq("user_id", user_id).execute()
        return len(response.data) > 0

    # MESSAGES
    def get_messages(self, conversation_id: str, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get messages for a conversation, checking that the user owns the conversation."""
        if not self.admin_client:
            return []
        
        # Verify ownership
        conv = self.get_conversation(conversation_id, user_id)
        if not conv:
            return []
            
        response = self.admin_client.table("messages").select("*")\
            .eq("conversation_id", conversation_id)\
            .order("created_at", desc=False)\
            .limit(limit).execute()
        return response.data

    def create_message(self, conversation_id: str, user_id: str, role: str, content: str, 
                       token_usage: Optional[Dict[str, int]] = None, response_time: Optional[float] = None,
                       reasoning: Optional[str] = None) -> Dict[str, Any]:
        """Insert a message into a conversation."""
        if not self.admin_client:
            raise Exception("Supabase client not initialized")
            
        data = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "role": role,
            "content": content
        }
        if token_usage:
            data["token_usage"] = token_usage
        if response_time is not None:
            data["response_time"] = response_time
        if reasoning is not None:
            data["reasoning"] = reasoning
            
        try:
            response = self.admin_client.table("messages").insert(data).execute()
        except Exception as e:
            # Fallback if the 'reasoning' column is missing from the database table
            if "reasoning" in data and "reasoning" in str(e):
                logger.warning("Failed to insert message with reasoning column. Retrying without reasoning...")
                data.pop("reasoning", None)
                response = self.admin_client.table("messages").insert(data).execute()
            else:
                raise e
        
        # Update conversation's updated_at timestamp
        self.admin_client.table("conversations").update({"updated_at": "now()"}).eq("id", conversation_id).execute()
        
        return response.data[0]

    # FAVORITES
    def get_favorites(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all favorited messages for a user with conversation titles and message content."""
        if not self.admin_client:
            return []
        response = self.admin_client.table("favorites")\
            .select("*, messages(*, conversations(title))")\
            .eq("user_id", user_id).execute()
        return response.data

    def toggle_favorite(self, user_id: str, message_id: str) -> Dict[str, Any]:
        """Toggle favorite status of a message."""
        if not self.admin_client:
            raise Exception("Supabase client not initialized")
            
        # Check if already exists
        exists_res = self.admin_client.table("favorites").select("*")\
            .eq("user_id", user_id).eq("message_id", message_id).execute()
            
        if exists_res.data:
            # Delete
            self.admin_client.table("favorites").delete()\
                .eq("user_id", user_id).eq("message_id", message_id).execute()
            return {"status": "removed", "message_id": message_id}
        else:
            # Insert
            res = self.admin_client.table("favorites").insert({
                "user_id": user_id,
                "message_id": message_id
            }).execute()
            return {"status": "added", "favorite": res.data[0]}

    # USER PREFERENCES
    def get_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user preferences."""
        if not self.admin_client:
            return {}
        response = self.admin_client.table("user_preferences").select("*")\
            .eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]
        else:
            # Create default preferences
            new_pref = self.admin_client.table("user_preferences").insert({"user_id": user_id}).execute()
            return new_pref.data[0] if new_pref.data else {}

    def update_preferences(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user preferences."""
        if not self.admin_client:
            raise Exception("Supabase client not initialized")
        updates["updated_at"] = "now()"
        response = self.admin_client.table("user_preferences").update(updates)\
            .eq("user_id", user_id).execute()
        return response.data[0] if response.data else {}

    # PROFILE
    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Get user profile."""
        if not self.admin_client:
            return {}
        response = self.admin_client.table("profiles").select("*")\
            .eq("id", user_id).execute()
        return response.data[0] if response.data else {}

    def update_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile (username, avatar_url)."""
        if not self.admin_client:
            raise Exception("Supabase client not initialized")
        updates["updated_at"] = "now()"
        response = self.admin_client.table("profiles").update(updates)\
            .eq("id", user_id).execute()
        return response.data[0] if response.data else {}

    # API USAGE LOGGING
    def log_api_usage(self, user_id: str, model: str, prompt_tokens: int, completion_tokens: int, estimated_cost: float) -> None:
        """Log token count and estimated cost of API requests."""
        if not self.admin_client:
            return
        try:
            self.admin_client.table("api_usage").insert({
                "user_id": user_id,
                "model": model,
                "tokens_prompt": prompt_tokens,
                "tokens_completion": completion_tokens,
                "estimated_cost": estimated_cost
            }).execute()
        except Exception as e:
            logger.error(f"Failed to log API usage: {e}")

    def get_api_usage_stats(self, user_id: str) -> Dict[str, Any]:
        """Fetch aggregated token usage and cost stats for dashboard."""
        if not self.admin_client:
            return {}
        try:
            response = self.admin_client.table("api_usage").select("*")\
                .eq("user_id", user_id).execute()
            data = response.data
            total_tokens = sum(x["tokens_prompt"] + x["tokens_completion"] for x in data)
            total_cost = sum(x["estimated_cost"] for x in data)
            model_counts = {}
            for x in data:
                m = x["model"]
                model_counts[m] = model_counts.get(m, 0) + 1
            return {
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 6),
                "request_count": len(data),
                "models_used": model_counts
            }
        except Exception as e:
            logger.error(f"Failed to fetch API usage stats: {e}")
            return {"total_tokens": 0, "total_cost": 0.0, "request_count": 0, "models_used": {}}

# Singleton supabase service instance
supabase_service = SupabaseService()
