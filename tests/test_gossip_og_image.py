"""Fetching an article's preview image must only ever contact public hosts,
including every hop of a redirect chain.

Driven through the agent's public `scrape_gossip()`. Stubs: Tavily's search
results, the HTTP transport (so the test sees every request actually made), and
DNS (so no test touches the network).
"""

import socket
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.agents.gossip_agent import GossipScraperAgent

ARTICLE = "https://variety.com/2026/tv/news/big-casting-news-1234567/"
PAGE_WITH_IMAGE = '<html><head><meta property="og:image" content="https://img.example.com/poster.jpg"></head></html>'

# hostname -> address it "resolves" to
DNS = {
    "variety.com": "93.184.216.34",
    "cdn.example-news.com": "93.184.216.35",
    "internal.corp.example": "10.0.0.5",
    "metadata.example": "169.254.169.254",
    "cgnat.example": "100.64.0.10",
}


def redirect(location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"location": location})


def page(html: str = PAGE_WITH_IMAGE) -> httpx.Response:
    return httpx.Response(200, text=html)


class FakeTavily:
    def __init__(self, url: str):
        self._url = url

    def search(self, **kwargs):
        return {"results": [{"url": self._url, "title": "Big Casting News", "content": "Some preview text."}]}


@pytest.fixture()
def scrape(db_session):
    """scrape(article_url, routes) -> (items, urls_requested).

    `routes` maps an absolute URL to the response the stub returns for it.
    """

    @contextmanager
    def session_factory():
        yield db_session
        db_session.flush()

    def fake_getaddrinfo(host, *args, **kwargs):
        if host not in DNS:
            raise socket.gaierror(f"unknown host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (DNS[host], 0))]

    async def run(article_url: str, routes: dict[str, httpx.Response]):
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return routes.get(str(request.url), httpx.Response(404))

        real_async_client = httpx.AsyncClient

        def stub_client(**kwargs):
            return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

        agent = GossipScraperAgent(session_factory=session_factory)
        agent.tavily = FakeTavily(article_url)
        with (
            patch("app.agents.gossip_agent.httpx.AsyncClient", side_effect=stub_client),
            patch("socket.getaddrinfo", side_effect=fake_getaddrinfo),
        ):
            items = await agent.scrape_gossip()
        return items, requested

    return run


def hosts(urls: list[str]) -> set[str]:
    return {httpx.URL(u).host for u in urls}


class TestOgImageRedirects:
    async def test_a_plain_article_still_gets_its_image(self, scrape):
        items, requested = await scrape(ARTICLE, {ARTICLE: page()})

        assert items[0]["image_url"] == "https://img.example.com/poster.jpg"
        assert hosts(requested) == {"variety.com"}

    async def test_a_redirect_to_another_public_host_is_followed(self, scrape):
        target = "https://cdn.example-news.com/story"
        items, requested = await scrape(ARTICLE, {ARTICLE: redirect(target), target: page()})

        assert items[0]["image_url"] == "https://img.example.com/poster.jpg"
        assert hosts(requested) == {"variety.com", "cdn.example-news.com"}

    async def test_a_relative_redirect_is_resolved_and_followed(self, scrape):
        moved = "https://variety.com/2026/tv/news/moved/"
        items, requested = await scrape(ARTICLE, {ARTICLE: redirect("/2026/tv/news/moved/"), moved: page()})

        assert requested == [ARTICLE, moved]
        assert items[0]["image_url"] == "https://img.example.com/poster.jpg"

    @pytest.mark.parametrize(
        "target",
        [
            "http://169.254.169.254/latest/meta-data/",  # link-local literal
            "http://127.0.0.1:8000/admin",  # loopback literal
            "http://10.1.2.3/",  # private literal
            "http://internal.corp.example/",  # name that resolves to a private address
            "http://metadata.example/",  # name that resolves to link-local
            "http://100.100.100.200/",  # carrier-grade NAT range (not public)
            "http://cgnat.example/",  # name that resolves into that range
            "http://224.0.0.1/",  # multicast
            "http://[::1]/",  # IPv6 loopback
            "http://[::ffff:10.0.0.1]/",  # IPv4-mapped private address
            "http://unresolvable.invalid/",  # does not resolve
            "file:///etc/passwd",  # not http(s)
            "gopher://variety.com/",  # not http(s)
        ],
    )
    async def test_a_redirect_to_a_non_public_target_is_never_requested(self, scrape, target):
        items, requested = await scrape(ARTICLE, {ARTICLE: redirect(target), target: page()})

        assert requested == [ARTICLE], f"unexpected requests: {requested}"
        assert items[0]["image_url"] is None  # the article itself is still stored

    async def test_a_public_hop_that_redirects_onward_to_a_private_target_is_stopped(self, scrape):
        hop = "https://cdn.example-news.com/step"
        private = "http://10.0.0.5/secret"
        _, requested = await scrape(ARTICLE, {ARTICLE: redirect(hop), hop: redirect(private), private: page()})

        assert private not in requested
        assert hosts(requested) == {"variety.com", "cdn.example-news.com"}

    async def test_a_redirect_loop_gives_up(self, scrape):
        a = "https://variety.com/2026/tv/news/redirecting-article-slug-one/"
        b = "https://variety.com/2026/tv/news/redirecting-article-slug-two/"
        items, requested = await scrape(a, {a: redirect(b), b: redirect(a)})

        assert items[0]["image_url"] is None
        assert len(requested) <= 5  # bounded, not endless

    async def test_an_article_url_that_is_itself_private_is_not_requested(self, scrape):
        private_article = "http://10.0.0.5/2026/tv/news/big-casting-news-1234567/"
        _, requested = await scrape(private_article, {private_article: page()})

        assert requested == []
