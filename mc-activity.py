#!/usr/bin/env python3
"""CLI to log/clear Live Activity entries in Mission Control board.json.

Usage:
  # Log activity
  python3 mc-activity.py --session "Claude Code" --text "Working on UI upgrade"
  python3 mc-activity.py --session "Claude Code" --text "Running tests" --label "CC" --color "#3b82f6"

  # Clear a specific entry
  python3 mc-activity.py --clear act-abc12345

  # Clear all activity
  python3 mc-activity.py --clear-all
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_lib import load_board, add_activity, remove_activity, clear_all_activity


def main():
    parser = argparse.ArgumentParser(description="Mission Control Live Activity CLI")
    parser.add_argument("--session", help="Session name (e.g. 'Claude Code')")
    parser.add_argument("--text", help="Activity description")
    parser.add_argument("--label", help="Short label (e.g. 'CC')", default=None)
    parser.add_argument("--color", help="Label color hex (e.g. '#3b82f6')", default=None)
    parser.add_argument("--clear", metavar="ID", help="Clear a specific activity entry by ID")
    parser.add_argument("--clear-all", action="store_true", help="Clear all activity entries")
    args = parser.parse_args()

    board = load_board()

    if args.clear_all:
        clear_all_activity(board)
        print("Cleared all activity entries.")
        return

    if args.clear:
        entry, err = remove_activity(board, args.clear)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)
        print(f"Cleared activity: {entry['id']}")
        return

    if not args.session or not args.text:
        parser.error("--session and --text are required when logging activity")

    entry = add_activity(board, args.session, args.text, label=args.label, color=args.color)
    print(f"Logged activity: {entry['id']} — {entry['text']}")


if __name__ == "__main__":
    main()
