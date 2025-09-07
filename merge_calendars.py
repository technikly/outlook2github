#!/usr/bin/env python3
"""
merge_calendars.py
Download multiple .ics feeds listed in a JSON file, prefix each event’s
summary with a calendar-specific prefix, merge feeds into one .ics file, and
— when two events share the *exact* same start, end *and* all‑day status —
combine their summaries instead of writing duplicate events.

Key rule updates
----------------
2025‑06‑17  • Preserve the original time‑zone of the first calendar contributing an event.
2025‑06‑17  • *New*: After all merging logic, **discard any event whose duration exceeds two days** (events up to and including two days remain).

Usage:
    python3 merge_calendars.py  [--json calendar_sources.json]  [--output combined.ics]

Dependencies:
    pip install requests icalendar pytz
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Dict, Tuple
from urllib.parse import urlparse

import requests
from icalendar import Calendar, Event, vText

JSON_DEFAULT = "calendar_sources.json"
OUTPUT_DEFAULT = "combined.ics"
HEADERS = {"User-Agent": "Calendar-Merger/1.3 (+https://example.com)"}
MAX_DAYS = 2  # Events longer than this are pruned

###############################################################################
# Helper functions
###############################################################################

def normalise_url(raw_url: str) -> str:
    """Strip any leading text before the first literal “http”."""
    http_pos = raw_url.find("http")
    if http_pos == -1:
        raise ValueError(f"Invalid URL string: {raw_url!r}")
    return raw_url[http_pos:]


def download_ics(url: str) -> Calendar:
    """Fetch an .ics feed and return it as an icalendar.Calendar object."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)

###############################################################################
# Duplicate‑detection utilities
###############################################################################

def _stringify_dt(dt_obj):
    """Return a comparable string form of DTSTART/DTEND without changing zones."""
    return dt_obj.isoformat()


def event_key(event: Event) -> Tuple[str, str | None, bool]:
    """Return a hashable key identifying an event’s timing."""
    dtstart = event.decoded("DTSTART")
    dtend = event.decoded("DTEND") if "DTEND" in event else None

    is_all_day = not isinstance(dtstart, _dt.datetime)
    return (
        _stringify_dt(dtstart),
        _stringify_dt(dtend) if dtend else None,
        is_all_day,
    )

###############################################################################
# Duration filter
###############################################################################

def event_duration_days(event: Event) -> float:
    """Return the event's duration in days (fractional allowed)."""
    dtstart = event.decoded("DTSTART")

    if "DTEND" in event:
        dtend = event.decoded("DTEND")
    elif "DURATION" in event:
        dtend = dtstart + event.decoded("DURATION")
    else:
        # No end: treat as zero‑length
        return 0.0

    # For DATE values (all‑day) dtend is exclusive per RFC 5545
    if isinstance(dtstart, _dt.date) and not isinstance(dtstart, _dt.datetime):
        duration = (dtend - dtstart).days
        return float(duration)

    # For DATETIME values
    delta = dtend - dtstart
    return delta.total_seconds() / 86400.0

###############################################################################
# Main merge routine
###############################################################################

def main(json_path: Path, output_path: Path) -> None:
    with json_path.open(encoding="utf-8") as fh:
        sources = json.load(fh)

    merged = Calendar()
    merged.add("prodid", "-//Merged via merge_calendars.py//EN")
    merged.add("version", "2.0")

    seen_events: Dict[Tuple[str, str | None, bool], Event] = {}

    for src in sources:
        if not src.get("Enabled", False):
            continue  # skip disabled feeds

        name   = src.get("Name", "Unnamed")
        prefix = src.get("Prefix", "")
        try:
            url = normalise_url(src["URL"])
        except (KeyError, ValueError) as e:
            print(f"Skipping {name}: {e}", file=sys.stderr)
            continue

        print(f"→ Downloading “{name}” from {urlparse(url).netloc} …")
        try:
            cal = download_ics(url)
        except Exception as e:
            print(f"   Failed ({e!s}); skipping.", file=sys.stderr)
            continue

        for component in cal.walk():
            if component.name != "VEVENT":
                if component.name not in {"VCALENDAR"}:
                    merged.add_component(component)
                continue

            new_event = Event.from_ical(component.to_ical())

            # Filter overlong events (strictly more than MAX_DAYS)
            if event_duration_days(new_event) > MAX_DAYS:
                continue

            # Prefix the summary
            summary = new_event.get("summary", vText(""))
            prefixed_summary = summary if str(summary).startswith(prefix) else f"{prefix}{summary}"
            new_event["summary"] = vText(prefixed_summary)

            # Duplicate detection & merging
            key = event_key(new_event)
            if key in seen_events:
                existing = seen_events[key]
                existing_summary = str(existing["summary"])
                if prefixed_summary not in existing_summary.split(", "):
                    existing["summary"] = vText(f"{existing_summary}, {prefixed_summary}")
                continue

            merged.add_component(new_event)
            seen_events[key] = new_event

    with output_path.open("wb") as fh:
        fh.write(merged.to_ical())

    print(f"\n✅ Done. Merged calendar written to: {output_path}")

###############################################################################
# CLI entry‑point
###############################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Merge multiple .ics feeds, deduplicating events with identical timing, "
            f"discarding events longer than {MAX_DAYS} days, and preserving the original "
            "time‑zone of the first event encountered."
        )
    )
    parser.add_argument("--json", default=JSON_DEFAULT, type=Path,
                        help=f"Path to JSON definition file (default: {JSON_DEFAULT})")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, type=Path,
                        help=f"Output .ics file path (default: {OUTPUT_DEFAULT})")
    args = parser.parse_args()

    main(args.json, args.output)
