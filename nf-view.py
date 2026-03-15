#!/usr/bin/env python3
"""View a specific NoteFlow entry with full details and subnotes."""

import argparse
import sys
from nf_lib import load_store, find_item


def main():
    parser = argparse.ArgumentParser(description="View a NoteFlow entry")
    parser.add_argument("--id", required=True, help="Item ID (e.g. nf-002)")
    args = parser.parse_args()

    store = load_store()
    item = find_item(store, args.id)
    if not item:
        print(f"Error: {args.id} not found", file=sys.stderr)
        sys.exit(1)

    # Header
    status_icon = "✓" if item["status"] == "done" else "○"
    print(f"[{item['id']}] {status_icon} {item['title']}")
    print(f"  Type: {item['type']} | Status: {item['status']}")

    if item.get("due"):
        print(f"  Due: {item['due']}")
    if item.get("remind"):
        print(f"  Reminder: {item['remind']}")
    if item.get("recurrence"):
        print(f"  Recurrence: {item['recurrence']}")
    if item.get("tags"):
        print(f"  Tags: {', '.join(item['tags'])}")
    if item.get("references"):
        print(f"  References:")
        for ref in item["references"]:
            print(f"    → {ref}")
    if item.get("linked_cards"):
        print(f"  Linked cards: {', '.join(item['linked_cards'])}")
    if item.get("project"):
        print(f"  Project: {item['project']}")

    # Body
    if item.get("body"):
        print(f"\n  {item['body']}")

    # Subnotes
    subnotes = item.get("subnotes", [])
    if subnotes:
        print(f"\n  Subnotes ({len(subnotes)}):")
        for i, sn in enumerate(subnotes):
            print(f"    [{i}] {sn['ts'][:16]} — {sn['text']}")
    else:
        print("\n  No subnotes.")

    # History
    history = item.get("history", [])
    if history:
        print(f"\n  History ({len(history)}):")
        for h in history[-5:]:  # Last 5 entries
            print(f"    {h['ts'][:16]} — {h['action']}")


if __name__ == "__main__":
    main()
