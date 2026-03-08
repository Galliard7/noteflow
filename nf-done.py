#!/usr/bin/env python3
"""NoteFlow: Mark an item as done."""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store, save_store, now_iso, SCRIPTS_DIR


def main():
    parser = argparse.ArgumentParser(description="Mark a NoteFlow item as done")
    parser.add_argument("--id", required=True, help="Item ID (e.g., nf-012)")
    args = parser.parse_args()

    store = load_store()

    target = None
    for item in store["items"]:
        if item["id"] == args.id:
            target = item
            break

    if not target:
        print(f"Error: Item {args.id} not found.")
        sys.exit(1)

    if target["status"] == "done":
        print(f"Item [{args.id}] {target['title']} is already done.")
        sys.exit(0)

    if target["status"] not in ("open", "snoozed"):
        print(f"Error: Cannot mark {args.id} as done (current status: {target['status']}).")
        sys.exit(1)

    target["status"] = "done"
    target["history"].append({"ts": now_iso(), "action": "done"})
    save_store(store)

    # Cancel any active cron job for this item
    had_cron = target.get("cron_installed", False)
    if had_cron:
        remind_script = os.path.join(SCRIPTS_DIR, "nf-remind.py")
        subprocess.run(["python3", remind_script, "--cancel", args.id])
        suffix = " (recurring reminder cancelled)"
    else:
        suffix = ""

    print(f"Done ✓ [{target['id']}] {target['title']}{suffix}")


if __name__ == "__main__":
    main()
