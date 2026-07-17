import base64
import logging
from typing import Optional, Dict, Any, Literal

logger = logging.getLogger(__name__)

# Maximum characters of PDF text to inject into the system prompt (≈ 12k tokens)
MAX_PDF_CHARS = 48_000

# Supported image MIME types for vision
SUPPORTED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/webp": "webp",
    "image/gif": "gif",
}

# Maximum file size: 10 MB
MAX_FILE_BYTES = 10 * 1024 * 1024


def detect_file_type(filename: str, content_type: str) -> Literal["pdf", "image", "unsupported"]:
    """
    Detect file type from filename extension and/or MIME type.
    """
    name_lower = filename.lower()
    if name_lower.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if content_type in SUPPORTED_IMAGE_TYPES:
        return "image"
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if name_lower.endswith(ext):
            return "image"
    return "unsupported"


def extract_pdf_text(file_bytes: bytes, filename: str = "document.pdf") -> Optional[str]:
    """
    Extract all text from a PDF using PyMuPDF.
    Returns the extracted text string, or None if extraction fails.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages_text = []
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            if text.strip():
                pages_text.append(f"--- Page {page_num + 1} ---\n{text.strip()}")
        doc.close()

        if not pages_text:
            logger.warning(f"No text extracted from PDF: {filename}")
            return None

        full_text = "\n\n".join(pages_text)
        # Truncate if very long
        if len(full_text) > MAX_PDF_CHARS:
            logger.info(f"PDF text truncated from {len(full_text)} to {MAX_PDF_CHARS} chars for '{filename}'")
            full_text = full_text[:MAX_PDF_CHARS] + "\n\n[... document truncated for length ...]"

        return full_text

    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Run: pip install PyMuPDF")
        return None
    except Exception as e:
        logger.error(f"Failed to extract text from PDF '{filename}': {e}")
        return None


def format_pdf_for_prompt(text: str, filename: str) -> str:
    """
    Format extracted PDF text into a system prompt block.
    """
    return (
        f"=== ATTACHED DOCUMENT: {filename} ===\n"
        f"{text}\n"
        f"=== END OF DOCUMENT ===\n"
        f"Use the document content above to accurately answer the user's question. "
        f"Reference specific parts when relevant."
    )


def encode_image_for_vision(file_bytes: bytes, content_type: str) -> Optional[Dict[str, Any]]:
    """
    Encode an image as a base64 data URI for use in vision API calls.
    Returns a dict with 'mime_type' and 'data_uri', or None on failure.
    """
    try:
        # Normalize MIME type
        mime = content_type.lower().strip()
        if mime not in SUPPORTED_IMAGE_TYPES:
            if "jpeg" in mime or "jpg" in mime:
                mime = "image/jpeg"
            elif "png" in mime:
                mime = "image/png"
            elif "webp" in mime:
                mime = "image/webp"
            elif "gif" in mime:
                mime = "image/gif"
            else:
                logger.error(f"Unsupported image MIME type: {content_type}")
                return None

        b64 = base64.b64encode(file_bytes).decode("utf-8")
        data_uri = f"data:{mime};base64,{b64}"
        return {
            "mime_type": mime,
            "data_uri": data_uri,
        }
    except Exception as e:
        logger.error(f"Failed to encode image for vision: {e}")
        return None


def process_uploaded_file(
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> Dict[str, Any]:
    """
    Main entry point. Processes an uploaded file and returns a structured result.

    Returns a dict:
      {
        "type": "pdf" | "image" | "error",
        "filename": str,
        "pdf_text_block": str | None,      # For PDFs: formatted prompt block
        "image_data_uri": str | None,      # For images: base64 data URI
        "mime_type": str | None,           # For images: MIME type
        "error": str | None,               # On failure
      }
    """
    result: Dict[str, Any] = {
        "type": "error",
        "filename": filename,
        "pdf_text_block": None,
        "image_data_uri": None,
        "mime_type": None,
        "error": None,
    }

    if len(file_bytes) > MAX_FILE_BYTES:
        result["error"] = f"File too large ({len(file_bytes) // (1024*1024):.1f} MB). Maximum allowed is 10 MB."
        return result

    file_type = detect_file_type(filename, content_type)

    if file_type == "unsupported":
        result["error"] = f"Unsupported file type '{content_type}'. Please upload a PDF or an image (PNG, JPG, WEBP, GIF)."
        return result

    if file_type == "pdf":
        text = extract_pdf_text(file_bytes, filename)
        if not text:
            result["error"] = "Could not extract text from the PDF. The file may be scanned/image-only or corrupted."
            return result
        result["type"] = "pdf"
        result["pdf_text_block"] = format_pdf_for_prompt(text, filename)

    elif file_type == "image":
        encoded = encode_image_for_vision(file_bytes, content_type)
        if not encoded:
            result["error"] = "Could not process the image file."
            return result
        result["type"] = "image"
        result["image_data_uri"] = encoded["data_uri"]
        result["mime_type"] = encoded["mime_type"]

    return result
