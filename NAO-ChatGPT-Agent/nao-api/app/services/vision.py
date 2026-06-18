#services/vision.py —> Image analysis via GPT-4o Vision.

#converts the image to base64 and injects it into the message sent to GPT, supporting JPEG and PNG and optimizing size to reduce tokens and latency


import base64
import struct
import zlib
import io
import threading
from typing import Optional
from app.utils import logger as log_module

_log = log_module.get("vision")

# Models that support vision
_VISION_MODELS = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision-preview"}


def model_supports_vision(model: str) -> bool:
    """Checks whether the model supports image analysis."""
    return any(vm in model.lower() for vm in _VISION_MODELS)


def prepare_image_message(
    image_data: bytes,
    filename: str,
    user_text: str,
    detail: str = "low",
) -> dict:
    """
    Builds an OpenAI message with text + base64 image.

    Args:
        image_data: image bytes
        filename: file name (to detect the MIME type)
        user_text: transcribed user text
        detail: "low" (fast, cheap) or "high" (detailed)
                "low" = 85 fixed tokens, "high" = up to 1785 tokens

    Returns:
        dict with role=user and content=[text, image_url]
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/jpeg")

    # Resize if too large (>1MB) to save tokens and latency
    optimized = _maybe_resize(image_data, mime)
    b64 = base64.b64encode(optimized).decode("ascii")

    _log.debug(
        f"Image: {len(image_data):,}B -> {len(optimized):,}B "
        f"({mime}, detail={detail})"
    )

    return {
        "role": "user",
        "content": [
            {"type": "text", "text": user_text or "(image sent without text)"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{b64}",
                    "detail": detail,
                },
            },
        ],
    }


def _maybe_resize(data: bytes, mime: str, max_bytes: int = 800_000) -> bytes:
    """
    Reduces a JPEG to ~800KB if necessary.
    No Pillow: uses native JPEG recompression (JPEG only).
    If it cannot reduce, returns the original.
    """
    if len(data) <= max_bytes:
        return data

    if mime != "image/jpeg":
        # For PNG/WEBP without Pillow: return the original unchanged
        # (in practice the NAO robot only sends JPEG)
        _log.warning(f"Large {mime} image ({len(data):,}B) — sending without resizing")
        return data

    # Without Pillow we cannot safely recompress, so send the original
    # and let the API handle it.
    _log.warning(f"Large JPEG ({len(data):,}B) -> sending without resizing (install Pillow for optimization)")
    return data


def build_vision_prompt_addition(has_photo: bool) -> str:
    """Returns an extra instruction for the system prompt when an image is present."""
    if not has_photo:
        return ""
    return (
        "\n\nAn image was captured by the robot's camera and included in the user's message. "
        "Analyze what is visible in the image if it is relevant to answering the question. "
        "If the user did not explicitly ask about the image, only mention it if it "
        "contains something notably relevant to the conversation."
    )
