"""Read-only audit of catalog identity problems (ADR-0006, issues #73 and #89).

Provider ids live in ``content_external_id``, whose primary key (provider, kind, external id)
already makes "one id on several titles of the same kind" impossible, so that check is gone.
Only SELECT statements are issued; nothing is written.

Two problem kinds are reported, each with a full count and a few sample rows:

* cross_type_ids: one provider id used by both a movie and a TV show.
* likely_duplicates: same normalised title, year and type (no shared provider id needed).
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.content import Content
from app.models.external_id import ContentExternalId

_MEMBER_LIMIT = 20


@dataclass
class Finding:
    count: int = 0
    samples: list[dict] = field(default_factory=list)


@dataclass
class AuditReport:
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
    ext = ContentExternalId
    # Same provider id used for both a movie and a TV show.
    shared = db.execute(
        select(ext.provider, ext.external_id)
        .where(ext.kind.in_(["movie", "tv_show"]))
        .group_by(ext.provider, ext.external_id)
        .having(func.count(func.distinct(ext.kind)) > 1)
        .order_by(ext.provider, ext.external_id)
    ).all()
    report.cross_type_ids.count = len(shared)
    for provider, value in shared[:sample_limit]:
        rows = db.execute(
            select(Content.id, Content.title, Content.content_type)
            .join(ext, ext.content_id == Content.id)
            .where(ext.provider == provider, ext.external_id == value, ext.kind.in_(["movie", "tv_show"]))
            .order_by(Content.id)
            .limit(_MEMBER_LIMIT)
        ).all()
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
