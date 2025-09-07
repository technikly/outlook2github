#!/usr/bin/env python3
"""
Interactive JSON editor for calendar source entries.

Each entry has:
    Name    : str
    URL     : str
    Prefix  : str
    Enabled : bool  (True ⇒ “Y”, False ⇒ “N”)

Run the script, then choose:
    1) Add   – enter a new record
    2) Edit  – toggle / delete an existing record
    3) Exit  – quit and save
"""

import json
import os
import sys
from pathlib import Path

FILE = Path("calendar_sources.json")


def load_data():
    if FILE.exists():
        try:
            with FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("⚠️  Could not read existing JSON – starting afresh.")
    return []


def save_data(data):
    with FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def prompt_non_empty(label):
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("Value cannot be blank – please try again.")


def prompt_yes_no(label):
    while True:
        value = input(f"{label} (Y/N): ").strip().upper()
        if value in {"Y", "N"}:
            return value == "Y"
        print("Please enter Y or N.")


def add_entry(data):
    print("\nAdd new entry")
    entry = {
        "Name":   prompt_non_empty("Name"),
        "URL":    prompt_non_empty("URL"),
        "Prefix": prompt_non_empty("Prefix"),
        "Enabled": prompt_yes_no("Enabled"),
    }
    data.append(entry)
    print("✅  Added.\n")


def list_entries(data):
    for idx, item in enumerate(data, start=1):
        status = "On" if item["Enabled"] else "Off"
        print(f"{idx}) {item['Name']} [{status}]")
    print()


def edit_entry(data):
    if not data:
        print("No entries to edit.\n")
        return

    list_entries(data)

    try:
        choice = int(input("Select number to edit (0 to cancel): "))
    except ValueError:
        print("Not a number.\n")
        return
    if choice == 0:
        return
    if 1 <= choice <= len(data):
        entry = data[choice - 1]
        while True:
            status = "On" if entry["Enabled"] else "Off"
            print(f"\nEditing “{entry['Name']}” (currently {status})")
            print("1) Toggle")
            print("2) Delete")
            print("3) Exit")
            sub = input("Select: ").strip()
            if sub == "1":
                entry["Enabled"] = not entry["Enabled"]
                print(f"🔁  Toggled to {'On' if entry['Enabled'] else 'Off'}.\n")
            elif sub == "2":
                del data[choice - 1]
                print("🗑️  Deleted.\n")
                break
            elif sub == "3":
                break
            else:
                print("Unknown option.")
    else:
        print("Number out of range.\n")


def main():
    data = load_data()
    while True:
        print("Main menu")
        print("1) Add")
        print("2) Edit")
        print("3) Exit")
        selection = input("Select: ").strip()
        if selection == "1":
            add_entry(data)
        elif selection == "2":
            edit_entry(data)
        elif selection == "3":
            save_data(data)
            print("💾  Saved. Goodbye!")
            sys.exit(0)
        else:
            print("Unknown option.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted – saving before exit.")
        save_data(load_data())
