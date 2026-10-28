"""Fish Audio TTS and its public voice library.

Fish is the first keyed engine: the admin stores an API key (Fernet-encrypted)
on the ``voice_model_configs`` row, and this module reads it through
``core.crypto`` — never through the channel credential store.
"""

import logging

logger = logging.getLogger(__name__)

_FISH_SORT_BY = ("score", "task_count", "created_at")
_FISH_CATALOG_PAGE_SIZE = 24

# Fish format name -> (mime type, sample rate). Ogg/Opus at 48 kHz is what
# Meta renders as a real voice note; mp3 only ever renders as a media bubble.
_FISH_FORMATS: dict[str, tuple[str, int | None]] = {
    "opus": ("audio/ogg", 48000),
    "mp3": ("audio/mpeg", None),
    "wav": ("audio/wav", None),
    "pcm": ("audio/pcm", 8000),
}


def voice_reference(engine, language: str, persona_id: str | None = None) -> str | None:
    """The voice persona for this language.

    An explicit persona (the caller picked one) wins, then a per-language pin,
    then the engine-wide multilingual voice. Without any pin Fish picks an
    arbitrary default per request, so the tenant would hear a different person
    every time.
    """
    if persona_id:
        return persona_id
    pins = engine.language_references or {}
    return pins.get(language) or engine.reference_id


async def synthesize(
    engine,
    text: str,
    language: str = "en",
    *,
    audio_format: str = "opus",
    persona_id: str | None = None,
) -> tuple[bytes, str] | None:
    """Render text with Fish Audio.

    ``audio_format`` is one of ``opus``/``mp3``/``wav``/``pcm``; unknown values
    fall back to ``opus`` because that is the format Meta renders as a voice
    note. Returns ``(bytes, mime_type)`` or None when the engine has no key or
    the request fails.
    """
    import httpx

    from ....core.crypto import decrypt_secret

    api_key = decrypt_secret(engine.key_encrypted) if engine.key_encrypted else None
    if not api_key:
        logger.info("Fish voice engine has no API key — sending text instead")
        return None

    fmt = audio_format if audio_format in _FISH_FORMATS else "opus"
    mime, sample_rate = _FISH_FORMATS[fmt]

    url = engine.api_url or "https://api.fish.audio/v1/tts"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if engine.api_model:
        headers["model"] = engine.api_model
    body: dict = {
        "text": text,
        "format": fmt,
        "normalize": True,
        "latency": "normal",
    }
    if sample_rate:
        body["sample_rate"] = sample_rate
    reference_id = voice_reference(engine, language, persona_id)
    if reference_id:
        body["reference_id"] = reference_id

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        logger.warning("Fish TTS failed (%s): %s", resp.status_code, resp.text[:200])
        return None
    audio = resp.content
    if not audio:
        return None
    return audio, mime


async def voice_catalog(api_key: str, sort_by: str = "task_count", page: int = 1) -> dict:
    """The fish.audio public voice library, slimmed for the admin picker.

    Fish's list endpoint ignores text search (verified live), but each model
    carries ``languages`` — the admin filters by language in the UI.
    Returns {"items": [{id, title, languages, tags, likes, uses}], "has_more"};
    raises ValueError with a readable message on failure.
    """
    import httpx

    if sort_by not in _FISH_SORT_BY:
        sort_by = "task_count"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://api.fish.audio/model",
            headers={"Authorization": f"Bearer {api_key}"},
            params={
                "page_size": _FISH_CATALOG_PAGE_SIZE,
                "page_number": max(1, page),
                "sort_by": sort_by,
            },
        )
    if resp.status_code >= 400:
        raise ValueError(f"fish.audio catalog failed ({resp.status_code})")
    data = resp.json()
    items = [
        {
            "id": it.get("_id", ""),
            "title": it.get("title") or "Untitled voice",
            "languages": it.get("languages") or [],
            "tags": (it.get("tags") or [])[:6],
            "likes": it.get("like_count"),
            "uses": it.get("task_count"),
        }
        for it in data.get("items", [])
        if it.get("_id")
    ]
    return {"items": items, "has_more": bool(data.get("has_more"))}
