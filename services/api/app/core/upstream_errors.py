"""Client-safe mapping for upstream/provider failures.

Provider drivers, storage SDKs and HTTP clients routinely put hostnames,
URLs, credentials or SQL in ``str(exc)``. That detail belongs in the logs
(and GlitchTip); the API response gets a generic message.
"""
import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DEFAULT_UPSTREAM_DETAIL = (
    "The upstream provider is temporarily unavailable. Try again shortly."
)


def upstream_http_error(
    exc: Exception,
    *,
    context: str,
    status_code: int = 502,
    detail: str = DEFAULT_UPSTREAM_DETAIL,
) -> HTTPException:
    """Log the real provider error and return a generic client error.

    Call as ``raise upstream_http_error(...) from None`` inside the except
    block so the response cannot inherit the provider's text.
    """
    logger.error("%s: %s", context, exc, exc_info=True)
    return HTTPException(status_code=status_code, detail=detail)
