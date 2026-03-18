import logging

logger = logging.getLogger(__name__)


def safe_error_response(e: Exception, context: str = "") -> str:
    """Log the full error internally and return a generic message to the client.

    Never expose raw exception messages (which may include DB table names,
    Supabase error details, or internal URLs) in HTTP responses.
    """
    label = f"[{context}] " if context else ""
    logger.error(f"Internal error {label}{e}", exc_info=True)
    return "An internal error occurred. Please try again later."
