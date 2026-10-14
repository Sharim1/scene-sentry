#!/usr/bin/env python3
"""
Scene Sentry management CLI.

Usage:
    python manage.py discover              # Run one scheduled batch (discovery_batch_size pages)
    python manage.py discover --full       # Exhaust all pages from all providers
    python manage.py discover --pages 20   # Fetch 20 pages per provider
    python manage.py discover --provider tvmaze          # Single provider only
    python manage.py discover --full --provider tvmaze   # Full sync, single provider
    python manage.py discover --status     # Show discovery state for all providers

    python manage.py enrich                # Enrich up to 50 sparse records
    python manage.py enrich --batch-size 200             # Larger batch
    python manage.py enrich --type tv_show               # Only TV shows
    python manage.py enrich --type movie                 # Only movies
    python manage.py enrich --id 3907                    # Enrich a specific content item
    python manage.py enrich --provider tvmaze            # Use only a specific provider
    python manage.py enrich --all                        # Loop until nothing left
    python manage.py enrich --status                     # Show how many records need enrichment

    python manage.py audit-ids             # Read-only report: ids shared by a movie and a show, likely duplicate titles
    python manage.py audit-ids --samples 25
    python manage.py review-list           # Read-only: titles parked because their ids conflict
    python manage.py failing-titles        # Titles whose refresh keeps failing (3+ by default)
    python manage.py lock-title 3907       # Protect a hand-edited title from refresh overwrites
    python manage.py unlock-title 3907     # Let refresh overwrite it again

    python manage.py recheck-sync          # Read-only: is each 'fully synced' end genuine?
    python manage.py recheck-sync --reset tvmaze/tv_show   # Owner's go only: unsync wrongly ended streams

    python manage.py fix-emails            # Backfill real emails from Clerk for placeholder users
    python manage.py fix-emails --dry-run  # Preview what would be updated
"""

import argparse
import logging
import sys

from app.utils.log_safety import quiet_http_client_logs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
quiet_http_client_logs()
logger = logging.getLogger("manage")


def _init_app():
    """Bootstrap database so models are available."""
    from app.database import init_db

    init_db()


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


def cmd_discover(args: argparse.Namespace) -> None:
    """Run content discovery from the CLI."""
    _init_app()

    if args.status:
        _show_discovery_status()
        return

    from app.database import db_session
    from app.services.content_discovery import ContentDiscoveryService

    with db_session() as db:
        svc = ContentDiscoveryService(db)

        if not svc.providers:
            logger.error("No active content providers. Check feature flags and API keys in .env")
            sys.exit(1)

        active = ", ".join(p.name for p in svc.providers)
        logger.info("Active providers: %s", active)

        if args.full:
            max_pg = args.max_pages or 500
            logger.info(
                "Full sync (max %d pages/provider%s)...",
                max_pg,
                f", provider={args.provider}" if args.provider else "",
            )
            result = svc.run_full_sync(
                provider_name=args.provider,
                max_pages=max_pg,
            )
        elif args.pages:
            logger.info(
                "Fetching %d pages per provider%s...",
                args.pages,
                f", provider={args.provider}" if args.provider else "",
            )
            result = svc.run_n_pages(
                pages=args.pages,
                provider_name=args.provider,
            )
        else:
            logger.info("Running one scheduled batch...")
            result = svc.run_scheduled_sync()

        logger.info(
            "Done — movies: %d, tv_shows: %d",
            result["movies"],
            result["tv_shows"],
        )


def _show_discovery_status():
    """Print the current discovery state for every provider/content_type pair."""
    from app.database import db_session
    from app.models.discovery_state import DiscoveryState

    with db_session() as db:
        rows = (
            db.query(DiscoveryState)
            .order_by(
                DiscoveryState.provider,
                DiscoveryState.content_type,
            )
            .all()
        )

    if not rows:
        print("No discovery state recorded yet.")
        return

    header = f"{'Provider':<12} {'Type':<10} {'Page':<6} {'Items':<8} {'Synced':<8} {'Last Run'}"
    print(header)
    print("-" * len(header))
    for r in rows:
        last = r.last_synced_at.strftime("%Y-%m-%d %H:%M") if r.last_synced_at else "never"
        print(
            f"{r.provider:<12} {r.content_type:<10} {r.last_page:<6} "
            f"{r.total_items_fetched:<8} {'yes' if r.fully_synced else 'no':<8} {last}"
        )


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------


def cmd_enrich(args: argparse.Namespace) -> None:
    """Run the detail enrichment pass from the CLI."""
    _init_app()

    from app.database import db_session
    from app.services.content_discovery import ContentDiscoveryService

    if args.status:
        _show_enrichment_status(args)
        return

    batch = args.batch_size or 50

    with db_session() as db:
        svc = ContentDiscoveryService(db)

        if not svc.providers:
            logger.error("No active content providers. Check feature flags and API keys in .env")
            sys.exit(1)

        kwargs = dict(
            batch_size=batch,
            content_type=args.type,
            content_id=args.id,
            provider_filter=args.provider,
        )

        if args.all:
            total = 0
            round_num = 0
            while True:
                round_num += 1
                logger.info("Enrichment round %d (batch_size=%d)...", round_num, batch)
                enriched = svc.enrich_sparse_content(**kwargs)
                total += enriched
                if enriched == 0:
                    break
            logger.info("All enrichment complete — %d total records", total)
        else:
            logger.info("Running detail enrichment (batch_size=%d)...", batch)
            enriched = svc.enrich_sparse_content(**kwargs)
            logger.info("Enriched %d content records", enriched)


def _show_enrichment_status(args: argparse.Namespace) -> None:
    """Print how many records still need enrichment."""
    from app.database import db_session
    from app.services.content_discovery import ContentDiscoveryService

    with db_session() as db:
        svc = ContentDiscoveryService(db)
        counts = svc.count_sparse(content_type=args.type)

    print("Enrichment backlog:")
    print(f"  TV shows missing episodes : {counts['tv_missing_episodes']}")
    print(f"  Records missing runtime   : {counts['missing_runtime']}")
    total = counts["tv_missing_episodes"] + counts["missing_runtime"]
    print(f"  Total sparse records      : {total}")


# ---------------------------------------------------------------------------
# fix-emails
# ---------------------------------------------------------------------------


def cmd_fix_emails(args: argparse.Namespace) -> None:
    """Backfill real emails and fix bad usernames for Clerk users."""
    _init_app()

    from app.database import db_session
    from app.models.user import User
    from app.services.identity_sync import fetch_clerk_user_email
    from app.services.identity_sync import is_placeholder_email as _is_placeholder_email
    from app.services.identity_sync import (
        is_placeholder_username as _is_placeholder_username,
    )

    with db_session() as db:
        users = db.query(User).filter(User.clerk_id.isnot(None)).all()

        needs_fix = [u for u in users if _is_placeholder_email(u.email) or _is_placeholder_username(u.username)]

        if not needs_fix:
            print("All Clerk users have valid emails and usernames. Nothing to do.")
            return

        print(f"Found {len(needs_fix)} user(s) needing fixes:\n")

        updated = 0
        for user in needs_fix:
            real_email = None
            changes = []

            if _is_placeholder_email(user.email):
                real_email = fetch_clerk_user_email(user.clerk_id)
                if real_email:
                    changes.append(f"email: {user.email} -> {real_email}")
                    if not args.dry_run:
                        user.email = real_email
                else:
                    changes.append(f"email: {user.email} -> [could not resolve]")

            if _is_placeholder_username(user.username):
                email_for_name = real_email or user.email
                if email_for_name and not _is_placeholder_email(email_for_name):
                    new_name = email_for_name.split("@")[0]
                else:
                    short_id = user.clerk_id.removeprefix("user_")[:8]
                    new_name = f"user_{short_id}"
                changes.append(f"username: {user.username} -> {new_name}")
                if not args.dry_run:
                    user.username = new_name

            if changes:
                updated += 1
                print(f"  {user.clerk_id[:16]}...: {', '.join(changes)}")

        if args.dry_run:
            print(f"\nDry run — {updated} user(s) would be updated. Re-run without --dry-run to apply.")
        else:
            db.commit()
            print(f"\nUpdated {updated} user(s).")


# ---------------------------------------------------------------------------
# audit-ids
# ---------------------------------------------------------------------------


def cmd_audit_ids(args: argparse.Namespace) -> None:
    """Read-only report of titles that would break a unique rule on provider ids."""
    _init_app()

    from app.database import SessionLocal
    from app.services.catalog_audit import format_report, run_read_only

    db = SessionLocal()
    try:
        print(format_report(run_read_only(db, sample_limit=args.samples)))
    finally:
        db.close()


def cmd_review_list(args: argparse.Namespace) -> None:
    """Read-only list of titles the sync parked instead of guessing."""
    _init_app()

    from app.database import SessionLocal
    from app.services.review_list import format_review, list_review

    db = SessionLocal()
    try:
        print(format_review(list_review(db)))
    finally:
        db.close()


def cmd_failing_titles(args: argparse.Namespace) -> None:
    """Read-only report of titles whose refresh keeps failing."""
    _init_app()

    from app.database import SessionLocal
    from app.services.refresh_planner import failing_titles

    db = SessionLocal()
    try:
        rows = failing_titles(db, args.min_failures)
        print(f"{len(rows)} titles with repeated refresh failures")
        for r in rows:
            print(f"  [{r.id}] {r.title} ({r.content_type}) attempts={r.refresh_attempts} error={r.last_error}")
    finally:
        db.close()


def _set_lock(content_id: int, locked: bool) -> None:
    _init_app()

    from app.database import SessionLocal
    from app.services.refresh_planner import set_refresh_lock

    db = SessionLocal()
    try:
        row = set_refresh_lock(db, content_id, locked)
        if row is None:
            print(f"No title with id {content_id}")
        else:
            print(f"{'Locked' if locked else 'Unlocked'} [{row.id}] {row.title} ({row.content_type})")
    finally:
        db.close()


def cmd_lock_title(args: argparse.Namespace) -> None:
    """Stop refresh from overwriting a hand-edited title."""
    _set_lock(args.content_id, True)


def cmd_unlock_title(args: argparse.Namespace) -> None:
    """Let refresh overwrite a title again."""
    _set_lock(args.content_id, False)


# ---------------------------------------------------------------------------
# recheck-sync
# ---------------------------------------------------------------------------


def cmd_recheck_sync(args: argparse.Namespace) -> None:
    """Report whether each 'fully synced' end is genuine; optionally reset wrong ones."""
    _init_app()

    from app.database import SessionLocal
    from app.services.providers.registry import get_active_providers
    from app.services.sync_recheck import format_report, recheck_streams, reset_wrong_streams

    db = SessionLocal()
    try:
        providers = get_active_providers()
        if not args.reset:
            print(format_report(recheck_streams(db, providers)))
            return
        streams = [tuple(r.split("/", 1)) for r in args.reset]
        done = reset_wrong_streams(db, providers, streams)
        for p, t in done:
            print(f"Reset {p}/{t}: fully_synced cleared, cursor kept.")
        for key in streams:
            if key not in done:
                print(f"Left alone {key[0]}/{key[1]}: not currently judged wrong.")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Scene Sentry management commands",
    )
    sub = parser.add_subparsers(dest="command")

    # -- discover --
    disc = sub.add_parser("discover", help="Run content discovery")
    disc.add_argument(
        "--full",
        action="store_true",
        help="Exhaust all pages from providers until catalog is fully synced",
    )
    disc.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Fetch N pages per provider (overrides discovery_batch_size)",
    )
    disc.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Upper bound for --full mode (default 500)",
    )
    disc.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Limit to a single provider (e.g. tvmaze, tvdb, omdb, tmdb)",
    )
    disc.add_argument(
        "--status",
        action="store_true",
        help="Show current discovery state and exit",
    )
    disc.set_defaults(func=cmd_discover)

    # -- enrich --
    enrich = sub.add_parser("enrich", help="Backfill missing detail data on sparse records")
    enrich.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of records to enrich per run (default 50)",
    )
    enrich.add_argument(
        "--type",
        type=str,
        default=None,
        choices=["movie", "tv_show"],
        help="Limit to a content type (movie or tv_show)",
    )
    enrich.add_argument(
        "--id",
        type=int,
        default=None,
        help="Enrich a specific content record by its database ID",
    )
    enrich.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Use only this provider for detail/episode lookups (e.g. tvmaze, tvdb, omdb)",
    )
    enrich.add_argument(
        "--all",
        action="store_true",
        help="Loop until no sparse records remain",
    )
    enrich.add_argument(
        "--status",
        action="store_true",
        help="Show enrichment backlog counts and exit",
    )
    enrich.set_defaults(func=cmd_enrich)

    # -- fix-emails --
    fe = sub.add_parser("fix-emails", help="Backfill real emails from Clerk for placeholder users")
    fe.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    fe.set_defaults(func=cmd_fix_emails)

    # -- audit-ids --
    audit = sub.add_parser("audit-ids", help="Read-only report of duplicate/conflicting provider ids")
    audit.add_argument("--samples", type=int, default=10, help="Sample rows per problem kind (default 10)")
    audit.set_defaults(func=cmd_audit_ids)

    review = sub.add_parser("review-list", help="Read-only list of titles parked because their ids conflict")
    review.set_defaults(func=cmd_review_list)

    failing = sub.add_parser("failing-titles", help="Read-only report of titles whose refresh keeps failing")
    failing.add_argument("--min-failures", type=int, default=None, help="Minimum failures (default: setting, 3)")
    failing.set_defaults(func=cmd_failing_titles)

    lock = sub.add_parser("lock-title", help="Protect a hand-edited title from refresh overwrites")
    lock.add_argument("content_id", type=int, help="Database id of the title")
    lock.set_defaults(func=cmd_lock_title)

    unlock = sub.add_parser("unlock-title", help="Let refresh overwrite a title again")
    unlock.add_argument("content_id", type=int, help="Database id of the title")
    unlock.set_defaults(func=cmd_unlock_title)

    # -- recheck-sync --
    recheck = sub.add_parser("recheck-sync", help="Check 'fully synced' streams; --reset to unsync wrong ones")
    recheck.add_argument(
        "--reset",
        nargs="+",
        metavar="PROVIDER/TYPE",
        help="Clear fully_synced on these streams if still judged wrong (needs the owner's go)",
    )
    recheck.set_defaults(func=cmd_recheck_sync)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
