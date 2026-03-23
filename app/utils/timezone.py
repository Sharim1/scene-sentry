"""
Timezone conversion helpers.

Uses the stdlib ``zoneinfo`` module (Python 3.9+). All datetimes stored in the
database are UTC; these functions convert at the boundary between user input /
display and the database layer.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones


def local_to_utc(naive_dt: datetime, tz_name: str) -> datetime:
    """Interpret *naive_dt* as local time in *tz_name* and return a
    timezone-aware UTC datetime."""
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, Exception):
        tz = ZoneInfo("UTC")
    local = naive_dt.replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def utc_to_local(utc_dt: datetime, tz_name: str) -> datetime:
    """Convert a UTC datetime to the user's local timezone.

    Handles both timezone-aware and naive (assumed UTC) input.
    """
    if utc_dt is None:
        return utc_dt
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, Exception):
        tz = ZoneInfo("UTC")
    return utc_dt.astimezone(tz)


# Curated list of common timezones for the settings dropdown.
COMMON_TIMEZONES: list[tuple[str, str]] = [
    ("UTC", "UTC (Coordinated Universal Time)"),
    ("US/Eastern", "US / Eastern (New York)"),
    ("US/Central", "US / Central (Chicago)"),
    ("US/Mountain", "US / Mountain (Denver)"),
    ("US/Pacific", "US / Pacific (Los Angeles)"),
    ("US/Hawaii", "US / Hawaii"),
    ("Canada/Eastern", "Canada / Eastern (Toronto)"),
    ("Canada/Pacific", "Canada / Pacific (Vancouver)"),
    ("Europe/London", "Europe / London"),
    ("Europe/Paris", "Europe / Paris"),
    ("Europe/Berlin", "Europe / Berlin"),
    ("Europe/Amsterdam", "Europe / Amsterdam"),
    ("Europe/Madrid", "Europe / Madrid"),
    ("Europe/Rome", "Europe / Rome"),
    ("Europe/Moscow", "Europe / Moscow"),
    ("Europe/Istanbul", "Europe / Istanbul"),
    ("Asia/Kolkata", "Asia / Kolkata (India)"),
    ("Asia/Dubai", "Asia / Dubai"),
    ("Asia/Karachi", "Asia / Karachi"),
    ("Asia/Dhaka", "Asia / Dhaka"),
    ("Asia/Bangkok", "Asia / Bangkok"),
    ("Asia/Singapore", "Asia / Singapore"),
    ("Asia/Hong_Kong", "Asia / Hong Kong"),
    ("Asia/Shanghai", "Asia / Shanghai"),
    ("Asia/Tokyo", "Asia / Tokyo"),
    ("Asia/Seoul", "Asia / Seoul"),
    ("Australia/Sydney", "Australia / Sydney"),
    ("Australia/Melbourne", "Australia / Melbourne"),
    ("Australia/Perth", "Australia / Perth"),
    ("Pacific/Auckland", "Pacific / Auckland (New Zealand)"),
    ("Africa/Cairo", "Africa / Cairo"),
    ("Africa/Lagos", "Africa / Lagos"),
    ("Africa/Johannesburg", "Africa / Johannesburg"),
    ("America/Sao_Paulo", "America / Sao Paulo"),
    ("America/Buenos_Aires", "America / Buenos Aires"),
    ("America/Mexico_City", "America / Mexico City"),
]
