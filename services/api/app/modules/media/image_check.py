"""Banner/promotion photo suitability check.

Google warns that a chosen cover photo is a *preference*, not a guarantee: a
photo Google considers low-quality or misrepresentative can be replaced by a
user-submitted one. This module scores an image against the deterministic
rules we can verify ourselves (format, minimum size, aspect, blur, exposure)
and — when a vision model is configured — asks the multimodal model for a
plain-language verdict. A ``suitable`` verdict never blocks publishing; it is
advice shown next to the upload.

The rule layer is deterministic and free, so it always runs. The AI verdict
only runs when ``settings.BANNER_VISION_MODEL`` is set; otherwise the payload
carries ``ai_verdict: null``.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from ...config import settings

logger = logging.getLogger(__name__)

MIN_WIDTH = 600
MIN_HEIGHT = 300
# Google shows cover/banner photos wide; a 16:9 image is 1.78. Anything
# substantially narrower or portrait is a warning, not an outright block.
GOOD_ASPECT_MIN = 1.4
GOOD_ASPECT_MAX = 2.2
# Variance of Laplacian below this reads as blurry to a human eye.
BLUR_VAR_THRESHOLD = 60.0
# Mean luma below/above these is too dark / too bright.
DARK_LUMA = 28.0
BRIGHT_LUMA = 232.0

_ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")

# Severity of each rule: "block" fails the overall check, "warn" lowers
# confidence but does not fail it.
_RULES: dict[str, dict[str, Any]] = {
    "format": {"label": "Format", "severity": "block", "weight": 45},
    "dimensions": {"label": "Size", "severity": "block", "weight": 30},
    "aspect": {"label": "Shape", "severity": "warn", "weight": 12},
    "blur": {"label": "Sharpness", "severity": "warn", "weight": 15},
    "exposure": {"label": "Exposure", "severity": "warn", "weight": 8},
}


def _load_image(data: bytes) -> Image.Image | None:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception:
        return None


def _luma_mean(image: Image.Image) -> float:
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    return float(stat.mean[0])


def _blur_variance(image: Image.Image) -> float:
    """Variance of the Laplacian; low variance = flat = blurry.

    Pillow's FIND_EDGES leaves the outermost border pixels unchanged, which
    would fake sharpness on any image. The border is cropped before the
    histogram (bounded to 256 buckets) is computed.
    """
    gray = image.convert("L")
    laplacian = gray.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.FIND_EDGES)
    interior = laplacian.crop((12, 12, laplacian.width - 12, laplacian.height - 12))
    stat = ImageStat.Stat(interior)
    mean = float(stat.mean[0])
    hist = interior.histogram()
    total = sum(hist) or 1
    return sum((i - mean) ** 2 * count for i, count in enumerate(hist)) / total


def _rule_result(key: str, passed: bool, note: str) -> dict[str, Any]:
    rule = _RULES[key]
    return {
        "key": key,
        "label": rule["label"],
        "pass": passed,
        "severity": rule["severity"],
        "note": note,
    }


def analyze_banner_image(
    data: bytes, *, filename: str = "", content_type: str | None = None
) -> dict[str, Any]:
    """Score an uploaded image as a Google banner/promotion photo.

    Returns suitable (yes/maybe/no), confidence 0-100, per-rule checks, a
    human summary and ai_verdict (None unless a vision model is configured).
    """
    image = _load_image(data)
    checks: list[dict[str, Any]] = []

    if image is None:
        checks.append(_rule_result("format", False, "The file is not a readable image."))
        checks.append(_rule_result("dimensions", False, "No image dimensions could be read."))
        checks.append(_rule_result("aspect", False, "Unknown."))
        checks.append(_rule_result("blur", False, "Unknown."))
        checks.append(_rule_result("exposure", False, "Unknown."))
        return _summarize(checks)

    fmt = (image.format or "").upper()
    checks.append(_rule_result(
        "format",
        fmt in _ALLOWED_FORMATS,
        f"{fmt} (use JPEG, PNG or WEBP)" if fmt not in _ALLOWED_FORMATS else f"{fmt}",
    ))

    width, height = image.size
    passed_dims = width >= MIN_WIDTH and height >= MIN_HEIGHT
    checks.append(_rule_result(
        "dimensions",
        passed_dims,
        f"{width}×{height}px"
        + ("" if passed_dims else f" — use at least {MIN_WIDTH}×{MIN_HEIGHT}px"),
    ))

    aspect = width / max(1, height)
    passed_aspect = GOOD_ASPECT_MIN <= aspect <= GOOD_ASPECT_MAX
    checks.append(_rule_result(
        "aspect",
        passed_aspect,
        f"{aspect:.2f}:1"
        + ("" if passed_aspect else " — banner photos look best wide (close to 16:9)"),
    ))

    blur_var = _blur_variance(image)
    passed_blur = blur_var >= BLUR_VAR_THRESHOLD
    checks.append(_rule_result(
        "blur",
        passed_blur,
        "looks sharp" if passed_blur else "looks blurry or low-resolution",
    ))

    luma = _luma_mean(image)
    passed_exposure = DARK_LUMA <= luma <= BRIGHT_LUMA
    checks.append(_rule_result(
        "exposure",
        passed_exposure,
        f"brightness {luma:.0f}/255"
        + ("" if passed_exposure else " — too dark or too bright"),
    ))

    return _summarize(checks)


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [c for c in checks if not c["pass"] and c["severity"] == "block"]
    warned = [c for c in checks if not c["pass"] and c["severity"] == "warn"]
    weight_lost = sum(_RULES[c["key"]]["weight"] for c in blocked + warned)
    confidence = max(0, min(100, 100 - weight_lost))

    if blocked:
        suitable = "no"
        summary = "Not suitable — fix the blocked checks below before publishing."
    elif warned:
        suitable = "maybe"
        summary = "Probably suitable — a few things could hurt how Google displays it."
    else:
        suitable = "yes"
        summary = "Looks suitable as a Google banner photo."

    return {
        "suitable": suitable,
        "confidence": round(confidence),
        "summary": summary,
        "checks": checks,
        "ai_verdict": None,
    }
