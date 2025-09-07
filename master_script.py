#!/usr/bin/env python3
"""
master_script.py
Merge enabled calendars (merge_calendars.py) then push the combined feed to
GitHub (push_to_github.py).

The script is path-independent: it always works out where it lives and calls the
helper scripts from that same directory.
"""
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
MERGE_SCRIPT = HERE / "merge_calendars.py"
PUSH_SCRIPT  = HERE / "push_to_github.py"
OUTPUT_FILE  = HERE / "combined.ics"

def run(cmd: list[str]) -> None:
    """Run a subprocess and abort on failure."""
    print(f"→ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode:
        sys.exit(f"❌ Step failed: {' '.join(cmd)}")

def main() -> None:
    # 1. Merge calendars
    run([sys.executable, str(MERGE_SCRIPT), "--output", str(OUTPUT_FILE)])

    # 2. Push the merged file to GitHub
    run([sys.executable, str(PUSH_SCRIPT), "--file", str(OUTPUT_FILE)])

    print("🎉 Calendar merge and GitHub push completed successfully.")

if __name__ == "__main__":
    main()
