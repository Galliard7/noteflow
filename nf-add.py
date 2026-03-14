#!/usr/bin/env python3
"""NoteFlow: Add a new item to the store."""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store, save_store, now_iso, format_id, SCRIPTS_DIR
from mc_lib import load_board, add_card


def main():
    parser = argparse.ArgumentParser(description="Add a NoteFlow item")
    parser.add_argument(
        "--type",
        required=True,
        choices=["task", "idea", "note", "reminder"],
        dest="item_type",
    )
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--due", default=None)
    parser.add_argument("--remind", default=None)
    parser.add_argument("--tags", default="")
    parser.add_argument(
        "--recurrence",
        choices=["daily", "weekdays", "weekly", "monthly"],
        default=None,
        help="Recurrence pattern for reminders",
    )
    parser.add_argument(
        "--linked-card",
        default=None,
        help="Mission Control card slug to link this item to",
    )
    args = parser.parse_args()

    store = load_store()
    item_id = format_id(store["next_id"])
    now = now_iso()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    item = {
        "id": item_id,
        "type": args.item_type,
        "status": "open",
        "title": args.title,
        "body": args.body,
        "tags": tags,
        "created": now,
        "due": args.due,
        "remind": args.remind,
        "recurrence": args.recurrence,
        "linked_cards": [args.linked_card] if args.linked_card else [],
        "cron_installed": False,
        "snoozed_until": None,
        "history": [{"ts": now, "action": "created"}],
    }

    # Auto-create MC card for tasks without a linked card
    mc_slug = None
    if args.item_type == "task" and not args.linked_card:
        try:
            board = load_board()
            card = add_card(board, title=args.title, description=args.body or "", status="pending")
            mc_slug = card["slug"]
            item["linked_cards"] = [mc_slug]
            item["history"].append({"ts": now_iso(), "action": f"linked to MC card {mc_slug}"})
        except Exception:
            pass  # non-fatal — card can be linked later via msync

    store["items"].append(item)
    store["next_id"] += 1
    save_store(store)

    # Auto-install cron job if remind time is set
    if args.remind:
        remind_script = os.path.join(SCRIPTS_DIR, "nf-remind.py")
        cmd = ["python3", remind_script, "--set", item_id]
        if args.recurrence:
            cmd.extend(["--recurrence", args.recurrence])
        subprocess.run(cmd)

    # Output confirmation
    parts = [f"Type: {args.item_type}"]
    if args.due:
        parts.append(f"Due: {args.due}")
    if args.remind:
        parts.append(f"Reminder: {args.remind}")
    if args.recurrence:
        parts.append(f"Recurs: {args.recurrence}")
    linked = args.linked_card or mc_slug
    if linked:
        parts.append(f"Linked: {linked}")

    print(f"Captured → [{item_id}] {args.title}")
    print(f"  {' | '.join(parts)}")
    print("  (saved — say 'undo' or adjust)")


if __name__ == "__main__":
    main()
