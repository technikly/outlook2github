#!/usr/bin/env python3
"""
push_to_github.py
Upload (create-or-update) a file in a GitHub repository using the REST API v3.

Usage:
    python3 push_to_github.py  --file combined.ics
Dependencies:
    pip install requests python-dotenv
Config:
    Reads the following environment variables (e.g. from a .env file):
        GITHUB_TOKEN       - required Personal Access Token with repo scope
        GITHUB_REPOSITORY  - required "username/reponame"
        GITHUB_BRANCH      - optional branch name (default: main)
        GITHUB_PATH        - optional path in repo (default: combined.ics)
        GITHUB_COMMIT_MSG  - optional commit message (default: Update file)
"""
from base64 import b64encode
from pathlib import Path
import argparse
import os
import sys
from dotenv import load_dotenv
import requests


def load_config() -> dict:
    load_dotenv()
    cfg = {
        "token": os.getenv("GITHUB_TOKEN"),
        "repository": os.getenv("GITHUB_REPOSITORY"),
        "branch": os.getenv("GITHUB_BRANCH", "main"),
        "path": os.getenv("GITHUB_PATH"),
        "commit_msg": os.getenv("GITHUB_COMMIT_MSG", "Update file"),
    }
    if not cfg["token"]:
        sys.exit("❌ Missing GITHUB_TOKEN")
    if not cfg["repository"]:
        sys.exit("❌ Missing GITHUB_REPOSITORY")
    return cfg

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
    remote_path = (cfg.get("path") or local_file.name).lstrip("/")
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

    cfg = load_config()
    push_file(cfg, args.file)

if __name__ == "__main__":
    main()
