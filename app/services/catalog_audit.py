"""Read-only audit of catalog identity problems (ADR-0006, issue #73).

Finds titles that would break a unique rule on (provider, kind, external id) before that
rule is added. Only SELECT statements are issued; nothing is written.

Three problem kinds are reported, each with a full count and a few sample rows:

* duplicate_provider_ids: one provider id used by several titles of the same kind.
* cross_type_ids: one provider id used by both a movie and a TV show.
* likely_duplicates: same normalised title, year and type (no shared provider id needed).
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.content import Content

# Provider id columns on content; the column name stands for the provider.
PROVIDER_ID_COLUMNS = {
    "tmdb": Content.tmdb_id,
    "imdb": Content.imdb_id,
    "tvdb": Content.tvdb_id,
    "tvmaze": Content.tvmaze_id,
    "isbn": Content.isbn,
}

_MEMBER_LIMIT = 20


@dataclass
class Finding:
    count: int = 0
    samples: list[dict] = field(default_factory=list)


@dataclass
class AuditReport:
    duplicate_provider_ids: Finding = field(default_factory=Finding)
    cross_type_ids: Finding = field(default_factory=Finding)
    likely_duplicates: Finding = field(default_factory=Finding)

    def as_dict(self) -> dict:
        return {name: {"count": f.count, "samples": f.samples} for name, f in vars(self).items()}


def _members(db: Session, filters: list):
    return db.execute(
        select(Content.id, Content.title, Content.content_type)
        .where(*filters)
        .order_by(Content.id)
        .limit(_MEMBER_LIMIT)
    ).all()


def _audit_provider_ids(db: Session, sample_limit: int, report: AuditReport) -> None:
    screen_kinds = ["movie", "tv_show"]
    for provider, col in PROVIDER_ID_COLUMNS.items():
        # Same id, same kind, several titles.
        groups = db.execute(
            select(Content.content_type, col)
            .where(col.is_not(None))
            .group_by(Content.content_type, col)
            .having(func.count(Content.id) > 1)
            .order_by(Content.content_type, col)
        ).all()
        report.duplicate_provider_ids.count += len(groups)
        for kind, value in groups:
            if len(report.duplicate_provider_ids.samples) >= sample_limit:
                break
            rows = _members(db, [Content.content_type == kind, col == value])
            report.duplicate_provider_ids.samples.append(
                {
                    "provider": provider,
                    "kind": kind,
                    "external_id": str(value),
                    "content_ids": [r.id for r in rows],
                    "titles": [r.title for r in rows],
                }
            )

        # Same id used for both a movie and a TV show.
        shared = (
            db.execute(
                select(col)
                .where(col.is_not(None), Content.content_type.in_(screen_kinds))
                .group_by(col)
                .having(func.count(func.distinct(Content.content_type)) > 1)
                .order_by(col)
            )
            .scalars()
            .all()
        )
        report.cross_type_ids.count += len(shared)
        for value in shared:
            if len(report.cross_type_ids.samples) >= sample_limit:
                break
            rows = _members(db, [col == value, Content.content_type.in_(screen_kinds)])
            report.cross_type_ids.samples.append(
                {
                    "provider": provider,
                    "external_id": str(value),
                    "content_ids": [r.id for r in rows],
                    "kinds": [r.content_type for r in rows],
                    "titles": [r.title for r in rows],
                }
            )


def _audit_likely_duplicates(db: Session, sample_limit: int, report: AuditReport) -> None:
    norm = func.lower(func.trim(Content.title))
    year = func.substr(Content.release_date, 1, 4)
    groups = db.execute(
        select(norm.label("title"), year.label("year"), Content.content_type)
        .where(Content.release_date.is_not(None))
        .group_by(norm, year, Content.content_type)
        .having(func.count(Content.id) > 1)
        .order_by(norm, year)
    ).all()
    report.likely_duplicates.count = len(groups)
    for title, yr, kind in groups[:sample_limit]:
        rows = _members(
            db, [norm == title, year == yr, Content.content_type == kind, Content.release_date.is_not(None)]
        )
        report.likely_duplicates.samples.append(
            {
                "title": title,
                "year": yr,
                "kind": kind,
                "content_ids": [r.id for r in rows],
                "titles": [r.title for r in rows],
            }
        )


def audit_catalog(db: Session, sample_limit: int = 10) -> AuditReport:
    """Run the audit with SELECT statements only."""
    report = AuditReport()
    _audit_provider_ids(db, sample_limit, report)
    _audit_likely_duplicates(db, sample_limit, report)
    return report


def run_read_only(db: Session, sample_limit: int = 10) -> AuditReport:
    """Audit inside a read-only transaction (enforced by Postgres) that is always rolled back."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    try:
        return audit_catalog(db, sample_limit)
    finally:
        db.rollback()


def format_report(report: AuditReport) -> str:
    """Plain-text summary: counts first, then sample rows per problem kind."""
    lines = []
    for name, finding in vars(report).items():
        lines.append(f"{name}: {finding.count}")
        for sample in finding.samples:
            lines.append(f"  - {sample}")
    return "\n".join(lines)
