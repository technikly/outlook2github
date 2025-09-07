#!/usr/bin/env python3
"""
download_calendars.py

Download multiple .ics feeds individually, remove events older than seven days,
and upload each cleaned feed to a GitHub repository folder.

Usage:
    python3 download_calendars.py [--json calendar_sources.json] [--folder calendars]

Dependencies:
    pip install requests icalendar python-dotenv
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from icalendar import Calendar

from push_to_github import load_config, push_file

HEADERS = {"User-Agent": "Calendar-Downloader/1.0 (+https://example.com)"}


def normalise_url(raw_url: str) -> str:
    """Strip any leading text before the first literal "http"."""
    http_pos = raw_url.find("http")
    if http_pos == -1:
        raise ValueError(f"Invalid URL string: {raw_url!r}")
    return raw_url[http_pos:]


def download_ics(url: str) -> Calendar:
    """Fetch an .ics feed and return an icalendar.Calendar object."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)


def _clone(component):
    """Return a detached copy of an icalendar component."""
    return component.__class__.from_ical(component.to_ical())


def filter_recent_events(cal: Calendar, threshold: _dt.datetime) -> Calendar:
    """Return a new calendar containing only events starting after ``threshold``."""
    new_cal = Calendar()
    for prop, val in cal.property_items():
        new_cal.add(prop, val)

    # Iterate over top-level components to avoid mutating the source calendar
    for component in list(cal.subcomponents):
        if component.name != "VEVENT":
            new_cal.add_component(_clone(component))
            continue

        dtstart = component.decoded("DTSTART")
        if isinstance(dtstart, _dt.datetime):
            thresh = threshold if dtstart.tzinfo else threshold.replace(tzinfo=None)
            if dtstart < thresh:
                continue
        else:  # date object
            if dtstart < threshold.date():
                continue

        new_cal.add_component(_clone(component))

    return new_cal


def slugify(name: str) -> str:
    """Return a filesystem-friendly version of ``name``."""
    return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")


def main(json_path: Path, local_folder: Path) -> None:
    with json_path.open(encoding="utf-8") as fh:
        sources = json.load(fh)

    local_folder.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    # ``GITHUB_PATH`` may point to a file (e.g. "calendars/combined.ics").
    # When uploading individual calendars we need just the directory portion,
    # otherwise the GitHub API will complain that a file exists where a
    # subdirectory is expected.  If no path is configured, default to the
    # provided local folder.
    base_remote = Path(cfg.get("path", local_folder))
    if base_remote.suffix:
        base_remote = base_remote.parent
    week_ago = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=7)

    for src in sources:
        if not src.get("Enabled", False):
            continue

        name = src.get("Name", "Unnamed")
        try:
            url = normalise_url(src["URL"])
        except (KeyError, ValueError) as e:
            print(f"Skipping {name}: {e}", file=sys.stderr)
            continue

        print(f"→ Downloading '{name}' from {urlparse(url).netloc} …")
        try:
            cal = download_ics(url)
        except Exception as e:
            print(f"   Failed ({e!s}); skipping.", file=sys.stderr)
            continue

        cleaned = filter_recent_events(cal, week_ago)
        filename = f"{slugify(name)}.ics"
        local_path = local_folder / filename
        with local_path.open("wb") as fh:
            fh.write(cleaned.to_ical())
        print(f"   Saved {local_path}")

        cfg["path"] = str(base_remote / filename)
        push_file(cfg, local_path)

    print("✅ All calendars processed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Download .ics feeds individually, prune events older than one week, "
            "and upload them to GitHub."
        )
    )
    parser.add_argument(
        "--json",
        default="calendar_sources.json",
        type=Path,
        help="Path to JSON definition file (default: calendar_sources.json)",
    )
    parser.add_argument(
        "--folder",
        default=Path("calendars"),
        type=Path,
        help="Local folder for cleaned calendars (default: ./calendars)",
    )
    args = parser.parse_args()

    main(args.json, args.folder)
