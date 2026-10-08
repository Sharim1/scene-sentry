"""Data-source credits: TheTVDB and TVmaze must be credited, with links, wherever
their metadata is viewed, and a full credits page must carry the licence notices.

TheTVDB (free tier) requires "attribution with a direct link to TheTVDB.com ...
displayed to end users viewing metadata"; TVmaze's CC BY-SA 4.0 licence allows a
reachable page with the required notices. Driven through HTTP only.
"""

from html.parser import HTMLParser
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.models.content import Content
from app.models.user import User

CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/"


class _Page(HTMLParser):
    """Collects links (href, visible text) and all visible text from a page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._link_text).split())))
            self._href = None

    def handle_data(self, data):
        self.text.append(data)
        if self._href is not None:
            self._link_text.append(data)


def parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def visible_text(page: _Page) -> str:
    return " ".join(" ".join(page.text).split())


def assert_has_credit(page: _Page, where: str) -> None:
    hrefs = [h for h, _ in page.links]
    tvdb = [
        (h, t) for h, t in page.links if h.startswith("https://thetvdb.com") or h.startswith("https://www.thetvdb.com")
    ]
    assert tvdb, f"{where}: no direct link to TheTVDB"
    assert any("TheTVDB" in t for _, t in tvdb), f"{where}: TheTVDB link has no readable name"
    assert "Metadata provided by" in visible_text(page), f"{where}: missing 'Metadata provided by TheTVDB'"
    assert any(h.startswith("https://www.tvmaze.com") for h in hrefs), f"{where}: no link to TVmaze"
    assert CC_BY_SA in hrefs, f"{where}: no link to the CC BY-SA 4.0 licence"
    assert "/credits" in hrefs, f"{where}: no link to the full credits page"


@pytest.fixture()
def world(db_session):
    """A signed-in user and one catalog title, with the DB and auth dependencies wired up."""
    from app.main import app

    user = User(id=1, username="tester", email="test@example.com")
    title = Content(title="Line of Duty", content_type="tv_show", release_date="2012-06-26", provider="tvmaze")
    db_session.add_all([user, title])
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app, user, title.id
    app.dependency_overrides.clear()


def _client(app, user=None) -> TestClient:
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    else:
        app.dependency_overrides.pop(get_current_user, None)
    return TestClient(app, raise_server_exceptions=True)


PUBLIC_PAGES = ["/", "/privacy", "/terms", "/contact", "/credits"]
SIGNED_IN_PAGES = ["/dashboard", "/library", "/reminders", "/gossip", "/search?q=duty", "/settings"]


@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_public_pages_credit_the_data_sources(world, path):
    app, _, _ = world
    with patch("app.main.init_db"), _client(app) as c:
        resp = c.get(path)

    assert resp.status_code == 200
    assert_has_credit(parse(resp.text), path)


@pytest.mark.parametrize("path", SIGNED_IN_PAGES)
def test_signed_in_pages_credit_the_data_sources(world, path):
    app, user, _ = world
    with patch("app.main.init_db"), _client(app, user) as c:
        resp = c.get(path)

    assert resp.status_code == 200
    assert_has_credit(parse(resp.text), path)


def test_title_detail_page_credits_the_data_sources(world):
    app, user, title_id = world
    with patch("app.main.init_db"), _client(app, user) as c:
        resp = c.get(f"/{title_id}")

    assert resp.status_code == 200
    assert_has_credit(parse(resp.text), f"/{title_id}")


def test_error_pages_credit_the_data_sources(world):
    app, user, _ = world
    with patch("app.main.init_db"), _client(app, user) as c:
        resp = c.get("/no/such/page")

    assert resp.status_code == 404
    assert_has_credit(parse(resp.text), "404 page")


class TestCreditsPage:
    @pytest.fixture()
    def page(self, world):
        app, _, _ = world
        with patch("app.main.init_db"), _client(app) as c:
            resp = c.get("/credits")
        assert resp.status_code == 200
        return parse(resp.text)

    def test_names_both_sources_with_the_licence_and_where_to_find_them(self, page):
        text = visible_text(page)
        assert "TheTVDB" in text and "TVmaze" in text
        assert "CC BY-SA 4.0" in text
        assert (CC_BY_SA, "CC BY-SA 4.0") in page.links

    def test_says_the_data_has_been_modified(self, page):
        """CC BY-SA requires indicating that the material was adapted."""
        text = visible_text(page).lower()
        assert "modified" in text or "adapted" in text or "reformat" in text

    def test_links_to_each_sources_own_site(self, page):
        hrefs = [h for h, _ in page.links]
        assert "https://thetvdb.com" in hrefs or "https://thetvdb.com/" in hrefs
        assert any(h.startswith("https://www.tvmaze.com") for h in hrefs)

    def test_does_not_claim_ownership_of_artwork(self, page):
        assert "property of their respective owners" in visible_text(page)

    def test_tells_rights_holders_how_to_ask_for_removal(self, page):
        text = visible_text(page)
        assert "Copyright and takedown requests" in text
        assert "remove" in text.lower()
        assert any(h == "/contact" and t for h, t in page.links)
