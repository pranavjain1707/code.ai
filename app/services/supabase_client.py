import os
import json
import uuid
import datetime
import logging
import threading
import socket
from urllib.parse import urlparse
from types import SimpleNamespace
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
from app.config.settings import settings

logger = logging.getLogger(__name__)

class LocalJsonDatabase:
    def __init__(self, filename="local_db.json"):
        self.filename = filename
        self.lock = threading.Lock()
        self.data = {
            "users": {},
            "profiles": {},
            "user_preferences": {},
            "conversations": {},
            "messages": {},
            "favorites": {},
            "api_usage": {}
        }
        self.load()

    def load(self):
        with self.lock:
            if os.path.exists(self.filename):
                try:
                    with open(self.filename, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        # Ensure all expected top-level keys exist and are dicts
                        for key in self.data:
                            if key in loaded:
                                self.data[key] = loaded[key]
                except Exception as e:
                    logger.error(f"Failed to load local DB: {e}")
            else:
                self.save_unlocked()

    def save_unlocked(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save local DB: {e}")

    def save(self):
        with self.lock:
            self.save_unlocked()

    def execute_query(self, query):
        with self.lock:
            table = query.table_name
            if table not in self.data:
                self.data[table] = {}

            if query.action == "insert":
                records_to_insert = query.action_data
                if not isinstance(records_to_insert, list):
                    records_to_insert = [records_to_insert]

                inserted_records = []
                for rec in records_to_insert:
                    rec_copy = dict(rec)
                    if "id" not in rec_copy:
                        rec_copy["id"] = str(uuid.uuid4())
                    if "created_at" not in rec_copy:
                        rec_copy["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    if "updated_at" not in rec_copy:
                        rec_copy["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    
                    self.data[table][rec_copy["id"]] = rec_copy
                    inserted_records.append(rec_copy)

                self.save_unlocked()
                return inserted_records

            # Filter records
            matching_ids = []
            for r_id, r in self.data[table].items():
                match = True
                for col, val in query.filters:
                    if r.get(col) != val:
                        match = False
                        break
                if not match:
                    continue
                for col, vals in query.in_filters:
                    if r.get(col) not in vals:
                        match = False
                        break
                if not match:
                    continue
                for col, pat in query.ilike_filters:
                    val_str = str(r.get(col) or "").lower()
                    pat_clean = pat.replace("%", "").lower()
                    if pat_clean not in val_str:
                        match = False
                        break
                if match:
                    matching_ids.append(r_id)

            if query.action == "delete":
                deleted_records = []
                for r_id in matching_ids:
                    deleted_records.append(self.data[table].pop(r_id))
                self.save_unlocked()
                return deleted_records

            if query.action == "update":
                updated_records = []
                for r_id in matching_ids:
                    r = self.data[table][r_id]
                    r_copy = dict(r)
                    for k, v in query.action_data.items():
                        if v == "now()":
                            v = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        r_copy[k] = v
                    r_copy["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    self.data[table][r_id] = r_copy
                    updated_records.append(r_copy)
                self.save_unlocked()
                return updated_records

            # Otherwise select
            selected_records = []
            for r_id in matching_ids:
                selected_records.append(dict(self.data[table][r_id]))

            # Joined selection for favorites
            if table == "favorites":
                for fav in selected_records:
                    msg_id = fav.get("message_id")
                    messages_table = self.data.get("messages", {})
                    msg = messages_table.get(msg_id)
                    if msg:
                        msg_copy = dict(msg)
                        conv_id = msg_copy.get("conversation_id")
                        conversations_table = self.data.get("conversations", {})
                        conv = conversations_table.get(conv_id)
                        if conv:
                            msg_copy["conversations"] = {"title": conv.get("title")}
                        else:
                            msg_copy["conversations"] = {"title": "Unknown"}
                        fav["messages"] = msg_copy
                    else:
                        fav["messages"] = None

            # Sorting
            if query.order_by:
                for col, desc in reversed(query.order_by):
                    selected_records.sort(
                        key=lambda r: (r.get(col) is not None, r.get(col) if r.get(col) is not None else ""),
                        reverse=desc
                    )

            # Limit
            if query.limit_val is not None:
                selected_records = selected_records[:query.limit_val]

            return selected_records


class MockAuth:
    def __init__(self, db):
        self.db = db

    def sign_up(self, credentials):
        email = credentials.get("email")
        password = credentials.get("password")
        options = credentials.get("options", {})
        metadata = options.get("data", {})
        username = metadata.get("username")

        with self.db.lock:
            # Check if user already exists
            for uid, u in self.db.data["users"].items():
                if u.get("email") == email:
                    raise Exception("User already registered")

            user_id = str(uuid.uuid4())
            user_record = {
                "id": user_id,
                "email": email,
                "password": password,
                "username": username,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            self.db.data["users"][user_id] = user_record

            # Simulating Auth Trigger
            profile = {
                "id": user_id,
                "email": email,
                "username": username or email.split("@")[0],
                "avatar_url": None,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            self.db.data["profiles"][user_id] = profile

            pref = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "theme": "dark",
                "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "system_prompt": "You are a helpful, smart, and friendly AI assistant.",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            self.db.data["user_preferences"][user_id] = pref

            self.db.save_unlocked()

        user_obj = SimpleNamespace(
            id=user_id,
            email=email,
            user_metadata={"username": username}
        )
        session_obj = SimpleNamespace(
            access_token=f"mock-jwt-token-{user_id}"
        )
        return SimpleNamespace(user=user_obj, session=session_obj)

    def sign_in_with_password(self, credentials):
        email = credentials.get("email")
        password = credentials.get("password")

        with self.db.lock:
            user_record = None
            for uid, u in self.db.data["users"].items():
                if u.get("email") == email:
                    user_record = u
                    break

            if not user_record or user_record.get("password") != password:
                raise Exception("Invalid login credentials")

            user_id = user_record["id"]
            username = user_record.get("username")

        user_obj = SimpleNamespace(
            id=user_id,
            email=email,
            user_metadata={"username": username}
        )
        session_obj = SimpleNamespace(
            access_token=f"mock-jwt-token-{user_id}"
        )
        return SimpleNamespace(user=user_obj, session=session_obj)

    def sign_out(self):
        pass

    def get_user(self, token):
        if not token or not token.startswith("mock-jwt-token-"):
            raise Exception("Invalid session token format")
        user_id = token.replace("mock-jwt-token-", "")

        with self.db.lock:
            user_record = self.db.data["users"].get(user_id)
            if not user_record:
                raise Exception("User session not found")
            email = user_record.get("email")
            username = user_record.get("username")

        user_obj = SimpleNamespace(
            id=user_id,
            email=email,
            user_metadata={"username": username}
        )
        return SimpleNamespace(user=user_obj)


class MockPostgrest:
    def __init__(self, db):
        self.db = db

    def auth(self, token):
        return self

    def table(self, table_name):
        return MockTable(self.db, table_name)


class MockTable:
    def __init__(self, db, table_name):
        self.db = db
        self.table_name = table_name
        self.filters = []
        self.in_filters = []
        self.ilike_filters = []
        self.order_by = []
        self.limit_val = None
        self.action = "select"
        self.action_data = None

    def select(self, columns="*"):
        self.action = "select"
        return self

    def insert(self, data):
        self.action = "insert"
        self.action_data = data
        return self

    def update(self, data):
        self.action = "update"
        self.action_data = data
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        self.in_filters.append((column, values))
        return self

    def ilike(self, column, pattern):
        self.ilike_filters.append((column, pattern))
        return self

    def order(self, column, desc=False):
        self.order_by.append((column, desc))
        return self

    def limit(self, val):
        self.limit_val = val
        return self

    def execute(self):
        result = self.db.execute_query(self)
        return SimpleNamespace(data=result)


class MockSupabaseClient:
    def __init__(self, db):
        self.auth = MockAuth(db)
        self.postgrest = MockPostgrest(db)
        self.table = self.postgrest.table


class SupabaseService:
    def __init__(self):
        # We perform a DNS resolution check to determine if the Supabase host is reachable.
        # If it fails, or if settings.SUPABASE_URL is a placeholder/empty, we use the local JSON DB.
        is_placeholder = not settings.SUPABASE_URL or "your-supabase-project" in settings.SUPABASE_URL
        dns_failed = False
        if not is_placeholder:
            try:
                parsed = urlparse(settings.SUPABASE_URL)
                host = parsed.netloc
                if ":" in host:
                    host = host.split(":")[0]
                socket.getaddrinfo(host, None)
            except Exception as e:
                logger.warning(f"Failed to resolve Supabase URL host {settings.SUPABASE_URL}: {e}. Switching to Local DB Fallback.")
                dns_failed = True

        if is_placeholder or dns_failed:
            logger.info("Initializing SupabaseService in LOCAL OFFLINE MODE (using local_db.json).")
            self.db = LocalJsonDatabase()
            self.client = MockSupabaseClient(self.db)
            self.admin_client = MockSupabaseClient(self.db)
        else:
            logger.info("Connecting to remote Supabase instance...")
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
