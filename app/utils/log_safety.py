"""Keep secrets out of logs."""

import logging


def quiet_http_client_logs() -> None:
    """Stop httpx logging every request URL at INFO.

    Several providers (OMDb, TMDb) pass their API key as a query parameter, and
    httpx's INFO line prints the full URL, so with INFO logging on, each request
    would write the key into the logs. Call after the process configures logging.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
