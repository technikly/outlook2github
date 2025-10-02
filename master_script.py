#!/usr/bin/env python3
"""
master_script.py

Clean, cron-safe workflow:
  1) Hard-reset local repo to origin/<branch> and clean (keep .env & venv/)
  2) Download/refresh individual calendars locally (7-day pruning)
  3) Build merged calendars/combined.ics locally (dedupe by exact timing, prefix summaries)
  4) Single git add/commit/push to origin/<branch> using token from sibling .env

Requires:
  pip install requests icalendar python-dotenv

Config (.env beside this file):
  GITHUB_TOKEN=...
  GITHUB_REPOSITORY=technikly/outlook2github
  GITHUB_BRANCH=main
  GITHUB_PATH=calendars/combined.ics
  GITHUB_COMMIT_MSG=Automated update of merged calendar
"""

from __future__ import annotations
from pathlib import Path
import argparse
import base64
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from typing import Dict, Tuple
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    import requests
    from icalendar import Calendar, Event, vText
except ImportError as e:
    sys.exit(f"❌ Missing dependency: {e}. Run: pip install requests icalendar python-dotenv")

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
load_dotenv(dotenv_path=ENV_FILE)

HEADERS_DL = {"User-Agent": "Calendar-Sync/2.0 (+outlook2github)"}

# Defaults that match your current repo layout / scripts
JSON_SOURCES_DEFAULT = HERE / "calendar_sources.json"
CAL_FOLDER_DEFAULT   = HERE / "calendars"


# ----------------------------- helpers: shell --------------------------------
def run(cmd: list[str], *, env: dict | None = None, allow_fail: bool = False) -> int:
    print("→ " + " ".join(cmd))
    r = subprocess.run(cmd, check=False, env=env)
    if r.returncode and not allow_fail:
        sys.exit(f"❌ Step failed: {' '.join(cmd)}")
    return r.returncode


def ensure_git_identity():
    def _get(key: str) -> str:
        r = subprocess.run(["git", "-C", str(HERE), "config", "--get", key],
                           check=False, stdout=subprocess.PIPE, text=True)
        return r.stdout.strip()
    if not _get("user.email"):
        run(["git", "-C", str(HERE), "config", "user.email",
             os.getenv("GIT_COMMIT_EMAIL", "automation@example")])
    if not _get("user.name"):
        run(["git", "-C", str(HERE), "config", "user.name",
             os.getenv("GIT_COMMIT_NAME", "Calendar Bot")])


def git_env_with_askpass(token: str, owner: str):
    """Create a temp GIT_ASKPASS helper to feed username/token without prompts."""
    tf = tempfile.NamedTemporaryFile("w", delete=False)
    tf.write(f"""#!/usr/bin/env bash
case "$1" in
  Username*) echo {shlex.quote(owner)} ;;
  Password*) echo {shlex.quote(token)} ;;
  *) echo ;;
esac
""")
    tf.flush()
    os.chmod(tf.name, 0o700)
    env = os.environ.copy()
    env["GIT_ASKPASS"] = tf.name
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env, tf.name


def force_sync(branch: str):
    if not (HERE / ".git").exists():
        print("ℹ️ Not a git repo; skipping force sync.")
        return
    run(["git", "-C", str(HERE), "fetch", "--prune"])
    run(["git", "-C", str(HERE), "checkout", branch])
    run(["git", "-C", str(HERE), "reset", "--hard", f"origin/{branch}"])
    # Keep .env and venv/ safe from cleaning
    run(["git", "-C", str(HERE), "clean", "-fd", "-e", ".env", "-e", "venv/"])
    print(f"✅ Force-synced to origin/{branch}")


# --------------------------- helpers: calendars -------------------------------
def normalise_url(raw_url: str) -> str:
    """Strip any leading text before the first literal http."""
    pos = raw_url.find("http")
    if pos == -1:
        raise ValueError(f"Invalid URL string: {raw_url!r}")
    return raw_url[pos:]


def download_ics(url: str) -> Calendar:
    resp = requests.get(url, headers=HEADERS_DL, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)


def slugify(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")


def _clone(component):
    return component.__class__.from_ical(component.to_ical())


def filter_recent_events(cal: Calendar, threshold: _dt.datetime) -> Calendar:
    """Keep only events starting after threshold (UTC-aware)."""
    new_cal = Calendar()
    for prop, val in cal.property_items():
        new_cal.add(prop, val)
    for component in list(cal.subcomponents):
        if component.name != "VEVENT":
            new_cal.add_component(_clone(component))
            continue
        dtstart = component.decoded("DTSTART")
        if isinstance(dtstart, _dt.datetime):
            thresh = threshold if dtstart.tzinfo else threshold.replace(tzinfo=None)
            if dtstart < thresh:
                continue
        else:  # date
            if dtstart < threshold.date():
                continue
        new_cal.add_component(_clone(component))
    return new_cal


def _stringify_dt(dt_obj):
    return dt_obj.isoformat()


def event_key(event: Event) -> Tuple[str, str | None, bool]:
    dtstart = event.decoded("DTSTART")
    dtend   = event.decoded("DTEND") if "DTEND" in event else None
    is_all_day = not isinstance(dtstart, _dt.datetime)
    return (_stringify_dt(dtstart), _stringify_dt(dtend) if dtend else None, is_all_day)


# ----------------------------- core workflow ---------------------------------
def refresh_individual_calendars(json_path: Path, local_folder: Path):
    """Download each enabled source, prune to last 7 days, save .ics locally."""
    with json_path.open(encoding="utf-8") as fh:
        sources = json.load(fh)
    local_folder.mkdir(parents=True, exist_ok=True)
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

    print("✅ All calendars refreshed locally.")


def build_merged_calendar(json_path: Path, output_path: Path):
    """Merge calendars per your rules (prefix summaries; dedupe by exact timing)."""
    with json_path.open(encoding="utf-8") as fh:
        sources = json.load(fh)

    merged = Calendar()
    merged.add("prodid", "-//Merged via master_script.py//EN")
    merged.add("version", "2.0")
    seen: Dict[Tuple[str, str | None, bool], Event] = {}

    for src in sources:
        if not src.get("Enabled", False):
            continue
        name   = src.get("Name", "Unnamed")
        prefix = src.get("Prefix", "")
        try:
            url = normalise_url(src["URL"])
        except (KeyError, ValueError) as e:
            print(f"Skipping {name}: {e}", file=sys.stderr)
            continue

        print(f"→ Downloading “{name}” for merge from {urlparse(url).netloc} …")
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
            summary = new_event.get("summary", vText(""))
            prefixed = summary if str(summary).startswith(prefix) else f"{prefix}{summary}"
            new_event["summary"] = vText(prefixed)

            key = event_key(new_event)
            if key in seen:
                existing = seen[key]
                existing_summary = str(existing["summary"])
                parts = [p.strip() for p in existing_summary.split(", ")] if existing_summary else []
                if str(prefixed) not in parts:
                    existing["summary"] = vText(f"{existing_summary}, {prefixed}" if existing_summary else str(prefixed))
                continue

            merged.add_component(new_event)
            seen[key] = new_event

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as fh:
        fh.write(merged.to_ical())
    print(f"✅ Merged calendar written to: {output_path}")


def main():
    ap = argparse.ArgumentParser(description="Clean pull → modify calendars → single commit & push")
    ap.add_argument("--json",   default=str(JSON_SOURCES_DEFAULT), help="Path to calendar_sources.json")
    ap.add_argument("--folder", default=str(CAL_FOLDER_DEFAULT),   help="Local calendars folder")
    ap.add_argument("--branch", default=os.getenv("GITHUB_BRANCH", "main"))
    ap.add_argument("--commit-msg", default=os.getenv("GITHUB_COMMIT_MSG", "Automated update of merged calendar"))
    ap.add_argument("--repo",   default=os.getenv("GITHUB_REPOSITORY", ""))
    ap.add_argument("--token",  default=os.getenv("GITHUB_TOKEN", ""))
    ap.add_argument("--path",   default=os.getenv("GITHUB_PATH", "calendars/combined.ics"),
                    help="Repo path for merged output (used only to decide output filename)")
    args = ap.parse_args()

    json_path   = Path(args.json)
    cal_folder  = Path(args.folder)
    combined_out = HERE / args.path  # write merged file at same repo path as your .env expects

    # 1) Ignore local state, pull remote
    force_sync(args.branch)

    # 2) Refresh individual calendars locally (no API pushes)
    refresh_individual_calendars(json_path, cal_folder)

    # 3) Build merged combined.ics locally
    build_merged_calendar(json_path, combined_out)

    # 4) Single git commit & push
    ensure_git_identity()
    run(["git", "-C", str(HERE), "add", "-A"])
    res = subprocess.run(["git", "-C", str(HERE), "commit", "-m", args.commit_msg],
                         check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if "nothing to commit" in (res.stdout + res.stderr):
        print("ℹ️ No repo changes to commit.")
        return

    if args.repo and args.token:
        owner = args.repo.split("/")[0]
        env, helper = git_env_with_askpass(args.token, owner)
        try:
            print(f"→ git -C {HERE} push origin {args.branch}")
            pr = subprocess.run(["git", "-C", str(HERE), "push", "origin", args.branch], check=False, env=env)
            if pr.returncode:
                sys.exit("❌ git push failed")
        finally:
            try:
                os.remove(helper)
            except OSError:
                pass
    else:
        # Fallback to interactive push if no token/repo provided
        run(["git", "-C", str(HERE), "push", "origin", args.branch])

    print(f"🎉 Completed: refreshed calendars, merged, and pushed to origin/{args.branch}")

if __name__ == "__main__":
    main()
