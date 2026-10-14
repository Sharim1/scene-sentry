"""Hand-edited titles are protected from refresh with lock-title / unlock-title (ADR-0006).

Driven through the manage.py commands with the in-memory test database: no network.
"""

import argparse
from unittest.mock import patch

import manage
from app.models.content import Content
from app.services.refresh_planner import set_refresh_lock
from tests.id_helpers import add_title


def run_command(db_session, command, content_id):
    # the command opens and closes its own session; hand it the test session and keep it open
    with (
        patch("manage._init_app"),
        patch("app.database.SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        command(argparse.Namespace(content_id=content_id))
    db_session.expire_all()


def test_lock_title_sets_refresh_locked(db_session, capsys):
    row = add_title(db_session, "Edited", "movie")

    run_command(db_session, manage.cmd_lock_title, row.id)

    assert db_session.get(Content, row.id).refresh_locked is True
    assert "Locked" in capsys.readouterr().out


def test_unlock_title_clears_refresh_locked(db_session):
    row = add_title(db_session, "Edited", "movie", refresh_locked=True)

    run_command(db_session, manage.cmd_unlock_title, row.id)

    assert db_session.get(Content, row.id).refresh_locked is False


def test_an_unknown_title_is_reported_not_created(db_session, capsys):
    run_command(db_session, manage.cmd_lock_title, 999999)

    assert "No title with id 999999" in capsys.readouterr().out


def test_set_refresh_lock_returns_none_for_an_unknown_title(db_session):
    assert set_refresh_lock(db_session, 999999, True) is None


def test_the_commands_are_registered(monkeypatch):
    seen = {}
    monkeypatch.setattr(manage, "cmd_lock_title", lambda a: seen.update(lock=a.content_id))
    monkeypatch.setattr(manage, "cmd_unlock_title", lambda a: seen.update(unlock=a.content_id))

    for argv, key in ((["lock-title", "5"], "lock"), (["unlock-title", "6"], "unlock")):
        with patch("sys.argv", ["manage.py", *argv]):
            manage.main()
        assert seen[key] == int(argv[1])
