# OpenRouter AI Chatbot

A production-ready, secure, and modern AI Chatbot web application built with **FastAPI**, **Supabase** (Database & Auth), and **OpenRouter** API. The interface is a premium ChatGPT-style glassmorphism Bootstrap 5 design that supports real-time Server-Sent Events (SSE) streaming, dark mode, markdown rendering, and math equations (LaTeX).

---

## Folder Structure

```
chat-ai-bot/
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── auth.py          # Signup, Login, Profile endpoints
│   │       ├── chat.py          # Blocking & SSE streaming routes
│   │       └── conversation.py  # History management, CRUD, Search, Favorites
│   ├── auth/
│   │   ├── __init__.py
│   │   └── jwt.py               # Dependency for token validation
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py          # Pydantic Settings management
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── security.py          # Rate limits & security headers
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── models.py            # Pydantic request models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── openrouter_client.py # OpenRouter API streaming client
│   │   ├── redis_cache.py       # Caching with memory fallback
│   │   └── supabase_client.py   # Auth and PostgreSQL service queries
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css        # Premium stylesheets
│   │   └── js/
│   │       └── app.js           # Client-side JavaScript controller
│   └── templates/
│       ├── auth.html            # Registration & login forms (Card flip)
│       └── index.html           # Main chat workspace & dashboard UI
├── tests/                       # Unit tests
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_chat.py
│   └── test_conversation.py
├── .env.example                 # Example config keys
├── Dockerfile                   # Multi-stage production container
├── docker-compose.yml           # Compose file (App + Redis)
├── requirements.txt             # Python packages list
├── supabase_schema.sql          # DB setup script
└── main.py                      # FastAPI initialization entrypoint
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your keys:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OPENROUTER_API_KEY` | Your OpenRouter API Key | |
| `OPENROUTER_BASE_URL` | OpenRouter completions URL | `https://openrouter.ai/api/v1` |
| `SUPABASE_URL` | Your Supabase Project API URL | |
| `SUPABASE_ANON_KEY` | Your Supabase Anon Public Key | |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role Key | Optional (falls back to Anon) |
| `JWT_SECRET` | Backend cookie session signing key | `supersecretjwtkey` |
| `REDIS_URL` | Cache server endpoint URL | `redis://localhost:6379/0` (fallback is in-memory) |
| `DEBUG` | Toggle FastAPI dev reload | `True` |
| `PORT` | Local runner execution port | `8000` |

---

## Supabase Database Setup

1. Log into your [Supabase Console](https://supabase.com).
2. Go to the **SQL Editor** of your project.
3. Paste the contents of `supabase_schema.sql` and click **Run**.
4. The tables, RLS policies, index optimizations, and auth triggers will be set up automatically.

---

## Installation & Running Locally

### Prerequisites
* Python 3.12+
* Redis (Optional: the backend falls back to in-memory caching if Redis is offline)

### Step 1: Clone and Install Dependencies
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### Step 3: Run the Server
```bash
python main.py
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Running with Docker Compose

Running via Docker Compose manages the setup of Redis and your web service automatically.

```bash
docker-compose up --build
```
Open [http://localhost:8000](http://localhost:8000).

---

## Running Tests

To run the unit tests:
```bash
pip install pytest pytest-asyncio
python -m pytest
```

---

## API Endpoints Documentation

### Authentication Router
* `POST /auth/signup`: Registers a new user.
* `POST /auth/login`: Logins a user and sets cookies.
* `POST /auth/logout`: Invalidates session and clears cookies.
* `GET /auth/profile`: Retrieves user profile and usage statistics.
* `PUT /auth/profile`: Updates profile username or avatar.
* `GET /auth/settings`: Retrieves preferences.
* `POST /auth/settings`: Saves user default model, system prompt, and theme.

### Conversations Management
* `POST /conversation`: Creates a new thread.
* `GET /conversation`: Lists non-archived user threads.
* `GET /conversation/{id}`: Retrieves details and messages for a thread.
* `PUT /conversation/{id}`: Renames, pins, or archives a thread.
* `DELETE /conversation/{id}`: Deletes a thread.
* `GET /history`: Keyword searches titles and message contents.
* `POST /favorite`: Toggles a message bookmark.
* `GET /conversation/models`: Lists cached OpenRouter LLM models.

### AI Inference
* `POST /chat`: Blocking request returning full AI answer.
* `POST /chat/stream`: Real-time Server-Sent Events (SSE) streaming.

---

## Troubleshooting Guide

#### 1. Rate Limiting (HTTP 429)
* **Cause**: You exceeded 60 requests/minute.
* **Fix**: Wait a minute. For production, adjust limit parameters in `app/middleware/security.py`.

#### 2. Failed to Connect to Redis
* **Result**: Look at logs. The app prints a warning but falls back to a safe in-memory dictionary.
* **Fix**: Ensure Redis container is running or update `REDIS_URL` in `.env`.

#### 3. Supabase Auth trigger fails
* **Result**: Signing up users fails to populate profiles table.
* **Fix**: Ensure your triggers and functions were fully executed using the SQL file.
