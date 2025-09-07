#!/usr/bin/env python3
"""
merge_calendars.py
Download multiple .ics feeds listed in a JSON file, prefix each event’s
summary with a calendar-specific prefix, and merge the lot into one .ics file.

Usage:
    python3 merge_calendars.py  [--json calendar_sources.json]  [--output combined.ics]

Dependencies:
    pip install requests icalendar pytz
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
import requests
from icalendar import Calendar, Event, vText

JSON_DEFAULT = "calendar_sources.json"
OUTPUT_DEFAULT = "combined.ics"
HEADERS = {"User-Agent": "Calendar-Merger/1.0 (+https://example.com)"}

def normalise_url(raw_url: str) -> str:
    """
    Some entries in the sample file have extra text before the actual
    https://… URL.  Strip everything up to the first ‘http’.
    """
    http_pos = raw_url.find("http")
    if http_pos == -1:
        raise ValueError(f"Invalid URL string: {raw_url!r}")
    return raw_url[http_pos:]

def download_ics(url: str) -> Calendar:
    """Fetch an .ics feed and return it as an icalendar.Calendar object."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)

def main(json_path: Path, output_path: Path) -> None:
    # Read calendar sources
    with json_path.open(encoding="utf-8") as fh:
        sources = json.load(fh)

    # Create a fresh calendar for the merge
    merged = Calendar()
    merged.add("prodid", "-//Merged via merge_calendars.py//EN")
    merged.add("version", "2.0")

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
                # Copy VTIMEZONE etc. directly
                if component.name not in {"VCALENDAR"}:
                    merged.add_component(component)
                continue

            # Clone the event to avoid cross-calendar side-effects
            new_event = Event.from_ical(component.to_ical())

            # Prefix the summary (title)
            summary = new_event.get("summary", vText(""))
            if not summary.startswith(prefix):
                new_event["summary"] = vText(f"{prefix}{summary}")

            # Add to merged calendar
            merged.add_component(new_event)

    # Write out the combined file
    with output_path.open("wb") as fh:
        fh.write(merged.to_ical())

    print(f"\n✅ Done. Merged calendar written to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge multiple .ics feeds.")
    parser.add_argument("--json",   default=JSON_DEFAULT,  type=Path,
                        help=f"Path to JSON definition file (default: {JSON_DEFAULT})")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, type=Path,
                        help=f"Output .ics file path (default: {OUTPUT_DEFAULT})")
    args = parser.parse_args()

    main(args.json, args.output)
