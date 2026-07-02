import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.redis_cache import cache_service

logger = logging.getLogger(__name__)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Inject standard security headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://*.supabase.co wss://*.supabase.co;"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Strict-Transport-Security (HTTPS only)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response

class RateLimitingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only rate limit POST requests to /chat (the expensive AI inference calls).
        # Auth, profile, settings, and conversation reads are excluded — they fire on
        # every page load and would hit the limit immediately under normal usage.
        is_chat_post = request.url.path.startswith("/chat") and request.method == "POST"

        if is_chat_post:
            client_ip = request.client.host if request.client else "unknown"
            key = f"rate_limit:chat:{client_ip}"

            try:
                current_hits = cache_service.get(key)
                if current_hits:
                    hits = int(current_hits)
                    # Allow 30 AI chat requests per minute per IP
                    if hits >= 30:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Chat rate limit exceeded. Maximum 30 messages per minute allowed. Please wait before sending another message."}
                        )
                    cache_service.set(key, hits + 1, expire_seconds=60)
                else:
                    cache_service.set(key, 1, expire_seconds=60)
            except Exception as e:
                # Fail open — if cache is unavailable, don't block users
                logger.error(f"Rate limiter cache error: {e}")

        return await call_next(request)
