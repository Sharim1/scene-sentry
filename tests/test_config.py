"""Tests for configuration loading."""

from app.config import Settings


def test_default_settings_load():
    """Settings should instantiate with defaults (no .env required)."""
    s = Settings(
        database_url="sqlite:///test.db",
        secret_key="test-key",
        _env_file=None,
    )
    assert s.app_name == "Scene Sentry"
    assert s.env == "development"


def test_clerk_not_configured_by_default():
    s = Settings(
        database_url="sqlite:///test.db",
        _env_file=None,
    )
    assert s.is_clerk_configured is False


def test_clerk_configured_when_keys_present():
    s = Settings(
        database_url="sqlite:///test.db",
        clerk_secret_key="sk_test_xxx",
        clerk_publishable_key="pk_test_xxx",
        _env_file=None,
    )
    assert s.is_clerk_configured is True


def test_authorized_parties_parsing():
    s = Settings(
        database_url="sqlite:///test.db",
        clerk_authorized_parties="http://localhost:3000, https://example.com",
        _env_file=None,
    )
    assert s.clerk_authorized_parties_list == [
        "http://localhost:3000",
        "https://example.com",
    ]
