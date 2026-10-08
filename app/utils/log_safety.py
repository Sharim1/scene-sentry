"""Keep secrets out of logs."""

import logging

import httpx


def quiet_http_client_logs() -> None:
    """Stop httpx logging every request URL at INFO.

    Several providers (OMDb, TMDb) pass their API key as a query parameter, and
    httpx's INFO line prints the full URL, so with INFO logging on, each request
    would write the key into the logs. Call after the process configures logging.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)


def describe_http_error(exc: Exception) -> str:
    """Short, key-safe description of a failed HTTP request, for logging.

    An httpx error's text includes the full request URL, and some providers take
    their API key as a query parameter, so never log ``str(exc)`` for those.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__
