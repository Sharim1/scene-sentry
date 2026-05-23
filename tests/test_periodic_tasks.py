"""Tests for Celery periodic tasks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_db_session():
    """Return a (mock_db_session_callable, mock_db) pair."""
    cm = MagicMock()
    mock_db = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_db)
    cm.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=cm), mock_db


def _run_coro(coro):
    """Execute a coroutine in a fresh event loop (bridges async mocks in sync Celery tasks)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── content_discovery_task ──────────────────────────────────────────────


class TestContentDiscoveryTask:
    def test_seeds_when_catalog_is_empty(self):
        from app.tasks.periodic import content_discovery_task

        mock_ds, _ = _mock_db_session()
        mock_svc = MagicMock()
        mock_svc.is_catalog_empty.return_value = True
        mock_svc.seed_catalog.return_value = 10
        mock_svc.enrich_sparse_content.return_value = 0

        with (
            patch("app.tasks.periodic.db_session", mock_ds),
            patch("app.tasks.periodic.ContentDiscoveryService", return_value=mock_svc),
        ):
            content_discovery_task.run()

        mock_svc.seed_catalog.assert_called_once()
        mock_svc.run_scheduled_sync.assert_not_called()

    def test_syncs_when_catalog_has_content(self):
        from app.tasks.periodic import content_discovery_task

        mock_ds, _ = _mock_db_session()
        mock_svc = MagicMock()
        mock_svc.is_catalog_empty.return_value = False
        mock_svc.run_scheduled_sync.return_value = {"movies": 5, "tv_shows": 3}
        mock_svc.enrich_sparse_content.return_value = 0

        with (
            patch("app.tasks.periodic.db_session", mock_ds),
            patch("app.tasks.periodic.ContentDiscoveryService", return_value=mock_svc),
        ):
            content_discovery_task.run()

        mock_svc.run_scheduled_sync.assert_called_once()
        mock_svc.seed_catalog.assert_not_called()


# ── content_enrichment_task ─────────────────────────────────────────────


class TestContentEnrichmentTask:
    def test_enriches_with_batch_size_50(self):
        from app.tasks.periodic import content_enrichment_task

        mock_ds, _ = _mock_db_session()
        mock_svc = MagicMock()
        mock_svc.enrich_sparse_content.return_value = 7

        with (
            patch("app.tasks.periodic.db_session", mock_ds),
            patch("app.tasks.periodic.ContentDiscoveryService", return_value=mock_svc),
        ):
            content_enrichment_task.run()

        mock_svc.enrich_sparse_content.assert_called_once_with(batch_size=50)


# ── gossip_scraping_task ────────────────────────────────────────────────


class TestGossipScrapingTask:
    def test_scrapes_up_to_20_tracked_titles(self):
        from app.tasks.periodic import gossip_scraping_task

        tracked = [f"Title {i}" for i in range(25)]
        mock_ds, _ = _mock_db_session()
        mock_repo = MagicMock()
        mock_repo.get_all_tracked_titles.return_value = tracked
        mock_gossip_svc = MagicMock()
        mock_gossip_svc.scrape_latest = AsyncMock(return_value=[])

        with (
            patch("app.tasks.periodic.db_session", mock_ds),
            patch("app.tasks.periodic.LibraryRepository", return_value=mock_repo),
            patch("app.tasks.periodic.GossipService", return_value=mock_gossip_svc),
            patch("app.tasks.periodic.asyncio.run", side_effect=_run_coro),
        ):
            gossip_scraping_task.run()

        mock_gossip_svc.scrape_latest.assert_called_once_with(tracked[:20])


# ── reranking_task ──────────────────────────────────────────────────────


class TestRerankingTask:
    def test_reranks_each_user(self):
        from app.tasks.periodic import reranking_task

        user_a, user_b = MagicMock(id=1, username="alice"), MagicMock(id=2, username="bob")
        mock_ds, mock_db = _mock_db_session()
        mock_db.query.return_value.all.return_value = [user_a, user_b]

        mock_svc = MagicMock()
        mock_svc.run_reranking = AsyncMock(return_value=5)

        with (
            patch("app.tasks.periodic.db_session", mock_ds),
            patch("app.tasks.periodic.RankingService", return_value=mock_svc),
            patch("app.tasks.periodic.asyncio.run", side_effect=_run_coro),
        ):
            reranking_task.run()

        assert mock_svc.run_reranking.call_count == 2
        mock_svc.run_reranking.assert_any_call(1)
        mock_svc.run_reranking.assert_any_call(2)


# ── reminder_task ───────────────────────────────────────────────────────


class TestReminderTask:
    def test_processes_due_reminders(self):
        from app.tasks.periodic import reminder_task

        mock_ds, _ = _mock_db_session()
        mock_svc = MagicMock()
        mock_svc.process_due_reminders.return_value = 3

        with (
            patch("app.tasks.periodic.db_session", mock_ds),
            patch("app.tasks.periodic.ReminderService", return_value=mock_svc),
        ):
            reminder_task.run()

        mock_svc.process_due_reminders.assert_called_once()


# ── cleanup_task ────────────────────────────────────────────────────────


class TestCleanupTask:
    def test_deletes_old_reminders_notifications_and_gossip(self):
        from app.tasks.periodic import cleanup_task

        mock_ds, mock_db = _mock_db_session()

        with patch("app.tasks.periodic.db_session", mock_ds):
            cleanup_task.run()

        assert mock_db.query.call_count == 3
