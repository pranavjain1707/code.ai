"""
Tests for the POST /chat/upload endpoint.
"""
import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def authenticated_user(mock_supabase):
    """Set up a mocked authenticated user."""
    mock_user = MagicMock(id="user-123", email="test@example.com")
    mock_supabase.get_user_from_token.return_value = mock_user
    mock_supabase.get_preferences.return_value = {
        "theme": "dark",
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "system_prompt": "You are a helpful assistant.",
    }
    mock_supabase.create_conversation.return_value = {"id": "conv-upload"}
    mock_supabase.create_message.return_value = {
        "id": "msg-upload",
        "role": "assistant",
        "content": "Here is the summary.",
    }
    mock_supabase.get_messages.return_value = []
    return mock_user


# Minimal valid PDF bytes (1-page skeleton)
MINIMAL_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n"
    b"0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>"
    b"startxref\n190\n%%EOF"
)

# Minimal 1x1 pixel PNG
MINIMAL_PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00'
    b'\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)

SAMPLE_SSE_CHUNKS = [
    'data: {"content": "Here is"}\n\n',
    'data: {"content": " the summary."}\n\n',
    'data: {"done": true, "prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "estimated_cost": 0.0}\n\n',
]


# ---------------------------------------------------------------------------
# /chat/upload endpoint tests
# ---------------------------------------------------------------------------

class TestChatUploadEndpoint:

    def test_upload_requires_authentication(self, client):
        """Returns 401 when no access token is provided."""
        files = {"file": ("test.pdf", io.BytesIO(MINIMAL_PDF_BYTES), "application/pdf")}
        response = client.post("/chat/upload", data={"message": "Summarize"}, files=files)
        assert response.status_code == 401

    def test_upload_pdf_success(self, client, mock_supabase, mock_local_model, authenticated_user):
        """Successful PDF upload returns SSE stream with conversation data."""
        pdf_block = "=== ATTACHED DOCUMENT: report.pdf ===\nExtracted text.\n=== END OF DOCUMENT ==="

        async def mock_stream(**kwargs):
            for chunk in SAMPLE_SSE_CHUNKS:
                yield chunk

        mock_local_model.stream_response = mock_stream

        with patch("app.api.routes.chat.process_uploaded_file", return_value={
            "type": "pdf",
            "filename": "report.pdf",
            "pdf_text_block": pdf_block,
            "image_data_uri": None,
            "mime_type": None,
            "error": None,
        }):
            client.cookies.set("access_token", "valid_token")
            response = client.post(
                "/chat/upload",
                data={"message": "Summarize this document"},
                files={"file": ("report.pdf", io.BytesIO(MINIMAL_PDF_BYTES), "application/pdf")},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "conv-upload" in response.text

    def test_upload_image_success(self, client, mock_supabase, mock_local_model, authenticated_user):
        """Successful image upload returns SSE stream via vision path."""
        async def mock_vision_stream(**kwargs):
            for chunk in SAMPLE_SSE_CHUNKS:
                yield chunk

        mock_local_model.stream_response_with_vision = mock_vision_stream

        with patch("app.api.routes.chat.process_uploaded_file", return_value={
            "type": "image",
            "filename": "photo.png",
            "pdf_text_block": None,
            "image_data_uri": "data:image/png;base64,abc123",
            "mime_type": "image/png",
            "error": None,
        }):
            client.cookies.set("access_token", "valid_token")
            response = client.post(
                "/chat/upload",
                data={"message": "What do you see?"},
                files={"file": ("photo.png", io.BytesIO(MINIMAL_PNG_BYTES), "image/png")},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    def test_upload_unsupported_file_type(self, client, mock_supabase, authenticated_user):
        """Returns 400 when an unsupported file type is uploaded."""
        with patch("app.api.routes.chat.process_uploaded_file", return_value={
            "type": "error",
            "filename": "data.csv",
            "pdf_text_block": None,
            "image_data_uri": None,
            "mime_type": None,
            "error": "Unsupported file type 'text/csv'. Please upload a PDF or an image.",
        }):
            client.cookies.set("access_token", "valid_token")
            response = client.post(
                "/chat/upload",
                data={"message": "Process this"},
                files={"file": ("data.csv", io.BytesIO(b"col1,col2\n1,2"), "text/csv")},
            )

        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_upload_file_too_large(self, client, mock_supabase, authenticated_user):
        """Returns 400 when the uploaded file exceeds 10 MB."""
        oversized = b"x" * (10 * 1024 * 1024 + 1)
        client.cookies.set("access_token", "valid_token")
        response = client.post(
            "/chat/upload",
            data={"message": "Process this"},
            files={"file": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
        )
        assert response.status_code == 400
        assert "too large" in response.json()["detail"].lower()

    def test_upload_creates_new_conversation(self, client, mock_supabase, mock_local_model, authenticated_user):
        """When no conversation_id is given, a new conversation is created and announced in SSE."""
        async def mock_stream(**kwargs):
            for chunk in SAMPLE_SSE_CHUNKS:
                yield chunk

        mock_local_model.stream_response = mock_stream

        with patch("app.api.routes.chat.process_uploaded_file", return_value={
            "type": "pdf",
            "filename": "notes.pdf",
            "pdf_text_block": "=== ATTACHED DOCUMENT: notes.pdf ===\nNotes.\n=== END OF DOCUMENT ===",
            "image_data_uri": None,
            "mime_type": None,
            "error": None,
        }):
            client.cookies.set("access_token", "valid_token")
            response = client.post(
                "/chat/upload",
                data={"message": "Key points?"},
                files={"file": ("notes.pdf", io.BytesIO(MINIMAL_PDF_BYTES), "application/pdf")},
            )

        assert response.status_code == 200
        mock_supabase.create_conversation.assert_called_once()
        assert "conv-upload" in response.text
        assert '"is_new_chat": true' in response.text


# ---------------------------------------------------------------------------
# file_processor unit tests
# ---------------------------------------------------------------------------

class TestFileProcessor:

    def test_detect_file_type_pdf(self):
        from app.services.file_processor import detect_file_type
        assert detect_file_type("report.pdf", "application/pdf") == "pdf"
        assert detect_file_type("REPORT.PDF", "application/octet-stream") == "pdf"

    def test_detect_file_type_image(self):
        from app.services.file_processor import detect_file_type
        assert detect_file_type("photo.png", "image/png") == "image"
        assert detect_file_type("shot.jpg", "image/jpeg") == "image"
        assert detect_file_type("anim.gif", "image/gif") == "image"

    def test_detect_file_type_unsupported(self):
        from app.services.file_processor import detect_file_type
        assert detect_file_type("data.csv", "text/csv") == "unsupported"
        assert detect_file_type("archive.zip", "application/zip") == "unsupported"

    def test_encode_image_for_vision_png(self):
        from app.services.file_processor import encode_image_for_vision
        result = encode_image_for_vision(MINIMAL_PNG_BYTES, "image/png")
        assert result is not None
        assert result["mime_type"] == "image/png"
        assert result["data_uri"].startswith("data:image/png;base64,")

    def test_encode_image_for_vision_unsupported_mime(self):
        from app.services.file_processor import encode_image_for_vision
        result = encode_image_for_vision(b"garbage", "application/octet-stream")
        assert result is None

    def test_format_pdf_for_prompt(self):
        from app.services.file_processor import format_pdf_for_prompt
        result = format_pdf_for_prompt("Page content here.", "my_report.pdf")
        assert "my_report.pdf" in result
        assert "Page content here." in result
        assert "=== END OF DOCUMENT ===" in result

    def test_process_uploaded_file_oversized(self):
        from app.services.file_processor import process_uploaded_file
        oversized = b"x" * (10 * 1024 * 1024 + 1)
        result = process_uploaded_file(oversized, "big.pdf", "application/pdf")
        assert result["type"] == "error"
        assert "too large" in result["error"].lower()

    def test_process_uploaded_file_unsupported(self):
        from app.services.file_processor import process_uploaded_file
        result = process_uploaded_file(b"col1,col2", "data.csv", "text/csv")
        assert result["type"] == "error"
        assert "Unsupported file type" in result["error"]
