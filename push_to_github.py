#!/usr/bin/env python3
"""
push_to_github.py
Upload (create-or-update) a file in a GitHub repository using the REST API v3.

Usage:
    python3 push_to_github.py  --file combined.ics
Dependencies:
    pip install requests
Config:
    Expects a file called config.json in the same directory with:
    {
      "token"      : "<PAT with repo scope>",
      "repository" : "username/reponame",
      "branch"     : "main",
      "path"       : "calendars/combined.ics",
      "commit_msg" : "Update merged calendar"
    }
"""
from base64 import b64encode
from pathlib import Path
import argparse
import json
import sys
import requests

CONFIG_PATH = Path(__file__).with_name("config.json")

def load_config(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"❌ Cannot find {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)

def github_request(method: str, url: str, token: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.update({
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Cal-Merger-Bot/1.0"
    })
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)

def push_file(cfg: dict, local_file: Path) -> None:
    if not local_file.is_file():
        sys.exit(f"❌ File not found: {local_file}")

    repo   = cfg["repository"]
    branch = cfg.get("branch", "main")
    remote_path = cfg.get("path", local_file.name).lstrip("/")
    token  = cfg["token"]
    url    = f"https://api.github.com/repos/{repo}/contents/{remote_path}"

    # 1. Check whether the file already exists to fetch its SHA
    resp = github_request("GET", url, token, params={"ref": branch})
    sha  = resp.json().get("sha") if resp.ok else None

    # 2. Prepare payload
    content_b64 = b64encode(local_file.read_bytes()).decode()
    payload = {
        "message": cfg.get("commit_msg", "Update file"),
        "branch" : branch,
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha  # required for updates

    # 3. PUT (create/update) the file
    r = github_request("PUT", url, token, json=payload)
    if r.status_code in (200, 201):
        action = "Updated" if sha else "Created"
        print(f"✅ {action} {remote_path} in {repo}@{branch}")
    else:
        sys.exit(f"❌ GitHub API error {r.status_code}: {r.text}")

def main():
    ap = argparse.ArgumentParser(description="Send a file to GitHub.")
    ap.add_argument("--file", default="combined.ics", type=Path,
                    help="Local file to upload (default: combined.ics)")
    args = ap.parse_args()

    cfg = load_config(CONFIG_PATH)
    push_file(cfg, args.file)

if __name__ == "__main__":
    main()
