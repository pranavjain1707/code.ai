import uvicorn
import logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.config.settings import settings
from app.api.routes import auth, chat, conversation
from app.api.routes import weather
from app.middleware.security import SecurityHeadersMiddleware, RateLimitingMiddleware
from app.services.supabase_client import supabase_service

# Setup logging configuration
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="A complete production-ready AI Chatbot utilizing OpenRouter and Supabase",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bind custom Security & Rate Limit Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitingMiddleware)

# Mount Static Assets and Templates directories
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Register Endpoint Routers
app.include_router(auth.router, prefix="", tags=["Authentication"])
app.include_router(chat.router, prefix="", tags=["AI Chat"])
app.include_router(conversation.router, prefix="", tags=["Conversations Management"])
app.include_router(weather.router, prefix="", tags=["Weather"])

# HTML PAGE VIEWS
@app.get("/", response_class=HTMLResponse)
async def serve_home_dashboard(request: Request):
    """
    Serves the main workspace chatbot view.
    Checks cookie token for basic redirection before rendering page.
    """
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/auth")
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/auth", response_class=HTMLResponse)
async def serve_auth_page(request: Request):
    """
    Serves the Auth page (Login/Signup flip card form).
    Validates the session cookie before redirecting to avoid infinite redirect loops
    caused by expired or invalid tokens that still exist in the cookie jar.
    """
    token = request.cookies.get("access_token")
    if token:
        # Validate the token — don't blindly redirect just because a cookie exists.
        # An expired token causes a loop: / -> verifyAuth 401 -> /auth -> / -> ...
        user = supabase_service.get_user_from_token(token)
        if user:
            return RedirectResponse(url="/")
        # Token is stale — clear it and fall through to the login page
        response = templates.TemplateResponse(request=request, name="auth.html")
        response.delete_cookie("access_token")
        return response
    return templates.TemplateResponse(request=request, name="auth.html")

# Global error exception catcher
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global unhandled error for {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "An internal server error occurred."}
    )

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG
    )
