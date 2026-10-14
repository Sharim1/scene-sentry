"""Short-lived per-job lease so two runs of the same periodic job never overlap.

The lease lives in Redis with an expiry, so a crashed run cannot block the job forever.
Tests swap the store (``_store``) for an in-memory fake.
"""

import functools
import logging
import secrets

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Extra seconds on top of the task's hard time limit before a lease expires on its own.
LEASE_GRACE_SECONDS = 30

_RELEASE_SCRIPT = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class RedisLeaseStore:
    def __init__(self, url):
        self._client = redis.Redis.from_url(url)

    def acquire(self, name, ttl_seconds):
        token = secrets.token_hex(8)
        if self._client.set(f"lease:{name}", token, nx=True, ex=int(ttl_seconds)):
            return token
        return None

    def release(self, name, token):
        self._client.eval(_RELEASE_SCRIPT, 1, f"lease:{name}", token)


_store = None


def _get_store():
    global _store
    if _store is None:
        _store = RedisLeaseStore(settings.redis_url)
    return _store


def leased(fn):
    """Wrap a bound periodic task body: skip at once if another run holds the job's lease."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        name = self.name.rsplit(".", 1)[-1]
        ttl = (self.time_limit or 0) + LEASE_GRACE_SECONDS
        store = _get_store()
        token = store.acquire(name, ttl)
        if token is None:
            logger.info("%s skipped: lease held by another run", name)
            return {"skipped": "lease_held", "job": name}
        try:
            return fn(self, *args, **kwargs)
        finally:
            store.release(name, token)

    wrapper.__leased__ = True
    return wrapper
