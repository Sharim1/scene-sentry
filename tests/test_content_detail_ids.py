"""The title page shows the IMDb link from the external-id table (ADR-0006, issue #88)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.models.user import User
from tests.id_helpers import add_title


@pytest.fixture()
def client(db_session):
    from app.main import app

    user = User(id=1, username="tester", email="test@example.com")
    db_session.add(user)
    db_session.commit()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.main.init_db"), TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def test_imdb_link_comes_from_the_external_id_table(client, db_session):
    row = add_title(db_session, "Dune", "movie", ids={"imdb": "tt1160419"})

    page = client.get(f"/{row.id}")

    assert page.status_code == 200
    assert "https://www.imdb.com/title/tt1160419" in page.text


def test_no_imdb_link_when_the_title_has_no_imdb_id(client, db_session):
    row = add_title(db_session, "Unknown", "movie", ids={"tvdb": 5})

    page = client.get(f"/{row.id}")

    assert page.status_code == 200
    assert "imdb.com/title" not in page.text
