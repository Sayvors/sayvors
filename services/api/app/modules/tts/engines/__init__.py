"""Provider clients for text-to-speech.

Every engine returns ``(audio_bytes, mime_type)`` or ``None``. ``None`` means
"this engine could not render" — no exception crosses the module boundary,
because the caller decides whether to degrade to text.
"""
