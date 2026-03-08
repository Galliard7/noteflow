#!/usr/bin/env python3
"""NoteFlow: List active items grouped by type."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store

TYPE_ORDER = ["task", "reminder", "idea", "note"]
TYPE_LABELS = {"task": "Tasks", "reminder": "Reminders", "idea": "Ideas", "note": "Notes"}


def main():
    store = load_store()
    active = [i for i in store["items"] if i["status"] in ("open", "snoozed")]

    if not active:
        print("No active items.")
        return

    grouped = {}
    for item in active:
        grouped.setdefault(item["type"], []).append(item)

    first = True
    for t in TYPE_ORDER:
        items = grouped.get(t, [])
        if not items:
            continue
        if not first:
            print()
        first = False
        print(f"## {TYPE_LABELS[t]}")
        for item in items:
            line = f"- [{item['id']}] {item['title']}"
            if item.get("due"):
                line += f" (due: {item['due']})"
            if item["status"] == "snoozed" and item.get("snoozed_until"):
                line += f" (snoozed until: {item['snoozed_until']})"
            print(line)


if __name__ == "__main__":
    main()
