#!/usr/bin/env python3
"""NoteFlow idea capture — raw-arg entry point for dispatch plugin.

Usage: python3 nf-idea.py <text>
  Bare call (no args) lists open ideas.
  With args, captures the text as a NoteFlow idea.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store, save_store, now_iso, format_id, store_lock


def list_ideas():
    store = load_store()
    ideas = [i for i in store["items"] if i["type"] == "idea" and i["status"] == "open"]
    if not ideas:
        print("No open ideas.")
        return
    print(f"💡 Ideas ({len(ideas)})")
    for i, item in enumerate(ideas, 1):
        print(f"  {i}. [{item['id']}] {item['title']}")


def add_idea(text):
    with store_lock():
        store = load_store()
        item_id = format_id(store["next_id"])
        now = now_iso()

        item = {
            "id": item_id,
            "type": "idea",
            "status": "open",
            "title": text,
            "body": text,
            "tags": [],
            "created": now,
            "due": None,
            "remind": None,
            "recurrence": None,
            "linked_cards": [],
            "project": None,
            "cron_installed": False,
            "snoozed_until": None,
            "history": [{"ts": now, "action": "created"}],
        }

        store["items"].append(item)
        store["next_id"] += 1
        save_store(store)

    print(f"Captured → [{item_id}] {text}")
    print("  Type: idea")
    print("  (saved — say 'undo' or adjust)")


def main():
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        list_ideas()
    else:
        add_idea(text)


if __name__ == "__main__":
    main()
