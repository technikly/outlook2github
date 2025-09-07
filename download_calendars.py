#!/usr/bin/env python3
"""
download_calendars.py
Download individual .ics calendars listed in a JSON file, drop events
that end before last week, and upload each cleaned feed to a folder in a
GitHub repository.

Usage:
    python3 download_calendars.py [--json calendar_sources.json]
                                  [--outdir calendars]
                                  [--github-folder calendars]

Dependencies:
    pip install requests icalendar python-dotenv
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from icalendar import Calendar

from push_to_github import load_config, push_file

HEADERS = {"User-Agent": "Calendar-Downloader/1.0 (+https://example.com)"}
JSON_DEFAULT = "calendar_sources.json"
OUTDIR_DEFAULT = Path("calendars")
GITHUB_FOLDER_DEFAULT = "calendars"

###############################################################################
# Helper functions
###############################################################################

def normalise_url(raw_url: str) -> str:
    """Strip any leading text before the first literal 'http'."""
    http_pos = raw_url.find("http")
    if http_pos == -1:
        raise ValueError(f"Invalid URL string: {raw_url!r}")
    return raw_url[http_pos:]


def download_ics(url: str) -> Calendar:
    """Fetch an .ics feed and return it as an icalendar.Calendar object."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)


def start_of_last_week(today: dt.date) -> dt.date:
    """Return the date of the Monday of last week."""
    return today - dt.timedelta(days=today.weekday() + 7)


def remove_old_events(cal: Calendar, threshold: dt.date) -> None:
    """Remove events that end before the threshold date in-place."""
    to_remove = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        if "DTEND" in component:
            dtend = component.decoded("DTEND")
        else:
            dtend = component.decoded("DTSTART")
        end_date = dtend.date() if isinstance(dtend, dt.datetime) else dtend
        if end_date < threshold:
            to_remove.append(component)
    for comp in to_remove:
        cal.subcomponents.remove(comp)


def slugify(name: str) -> str:
    """Return a filesystem-friendly version of a name."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    return slug.strip("_") or "calendar"


###############################################################################
# Main routine
###############################################################################

def main(json_path: Path, outdir: Path, github_folder: str) -> None:
    with json_path.open(encoding="utf-8") as fh:
        sources = json.load(fh)

    outdir.mkdir(parents=True, exist_ok=True)
    cfg_base = load_config()
    threshold = start_of_last_week(dt.date.today())

    for src in sources:
        if not src.get("Enabled", False):
            continue
        name = src.get("Name", "Unnamed")
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

        remove_old_events(cal, threshold)
        filename = slugify(name) + ".ics"
        local_path = outdir / filename
        local_path.write_bytes(cal.to_ical())

        cfg = cfg_base.copy()
        cfg["path"] = f"{github_folder.rstrip('/')}/{filename}"
        cfg["commit_msg"] = f"Update {filename}"
        push_file(cfg, local_path)

    print("\n✅ Done. Calendars downloaded, cleaned, and uploaded.")


###############################################################################
# CLI entry-point
###############################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download calendars, remove events before last week, and push to GitHub."
    )
    parser.add_argument("--json", default=JSON_DEFAULT, type=Path,
                        help=f"Path to JSON definition file (default: {JSON_DEFAULT})")
    parser.add_argument("--outdir", default=OUTDIR_DEFAULT, type=Path,
                        help=f"Directory to save cleaned .ics files (default: {OUTDIR_DEFAULT})")
    parser.add_argument("--github-folder", default=GITHUB_FOLDER_DEFAULT,
                        help=f"Folder in the GitHub repo to store files (default: {GITHUB_FOLDER_DEFAULT})")
    args = parser.parse_args()

    main(args.json, args.outdir, args.github_folder)
