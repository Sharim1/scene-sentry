"""Client-certificate TLS material for the database connection."""

import base64
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.database import tls_connect_args


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_no_tls_material_returns_no_connect_args():
    cfg = SimpleNamespace(database_ssl_ca_b64=None, database_ssl_cert_b64=None, database_ssl_key_b64=None)
    assert tls_connect_args(cfg) == {}


def test_tls_material_written_to_private_files():
    cfg = SimpleNamespace(
        database_ssl_ca_b64=_b64("CA PEM"),
        database_ssl_cert_b64=_b64("CERT PEM"),
        database_ssl_key_b64=_b64("KEY PEM"),
    )
    args = tls_connect_args(cfg)

    assert set(args) == {"sslrootcert", "sslcert", "sslkey"}
    contents = {name: Path(path).read_bytes() for name, path in args.items()}
    assert contents == {"sslrootcert": b"CA PEM", "sslcert": b"CERT PEM", "sslkey": b"KEY PEM"}
    for path in args.values():
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700


def test_partial_tls_material_is_rejected():
    with pytest.raises(ValueError, match="must be set together"):
        Settings(database_ssl_ca_b64=_b64("CA PEM"))
