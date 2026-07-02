import os
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Force override local .env variables over system-wide environment variables
load_dotenv(override=True)

class Settings(BaseSettings):
    APP_NAME: str = "Local AI Chatbot"
    DEBUG: bool = True
    PORT: int = 8000
    JWT_SECRET: str = "supersecretjwtkey"

    # Docker Model Runner Settings
    DOCKER_MODEL_RUNNER_URL: str = "http://localhost:12434/v1"

    # Supabase Settings
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # Redis Settings
    REDIS_URL: Optional[str] = None

    # Configure Pydantic to read from environment variables and dotenv file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings
settings = Settings()
