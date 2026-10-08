"""Test helpers for building genuinely signed Clerk-style handshake JWTs.

Only Clerk's network boundary is faked: the JWKS endpoint is stubbed to serve
the public half of a throwaway RSA key. Signature, expiry and key-id checks run
for real inside the Clerk SDK, so a forged or expired token is rejected by the
same code path as in production.
"""

import time
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

# The SDK's JWKS network call; the one thing we stub.
JWKS_FETCH = "clerk_backend_api.security.verifytoken._fetch_jwks_async"


class ClerkSigner:
    """A throwaway Clerk signing key plus the JWKS document that publishes it."""

    def __init__(self) -> None:
        self.kid = f"ins_test_{uuid.uuid4().hex}"  # unique so the SDK's key cache never crosses tests
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._private_pem = self._private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    @property
    def jwks(self) -> dict:
        jwk = RSAAlgorithm.to_jwk(self._private.public_key(), as_dict=True)
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def handshake_jwt(
        self,
        cookie_instructions: list[str],
        *,
        expires_in: int = 60,
        kid: str | None = None,
        cat: str | None = None,
    ) -> str:
        now = int(time.time())
        payload = {"handshake": cookie_instructions, "iat": now - 1, "exp": now + expires_in}
        headers = {"kid": kid or self.kid}
        if cat is not None:
            headers["cat"] = cat  # Clerk's token-category tag in the JOSE header
        return jwt.encode(payload, self._private_pem, algorithm="RS256", headers=headers)


@contextmanager
def clerk_jwks(signer: ClerkSigner):
    """Serve `signer`'s public key as Clerk's JWKS for the duration of the block."""
    with patch(JWKS_FETCH, new_callable=AsyncMock, return_value=signer.jwks):
        yield
