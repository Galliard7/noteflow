#!/usr/bin/env python3
"""CLI to add a progress comment to a Mission Control card."""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_lib import load_board, add_comment, find_card


def main():
    parser = argparse.ArgumentParser(description="Add a comment to a Mission Control card")
    parser.add_argument("--plan", required=True, help="Card slug (e.g. 'token-optimization')")
    parser.add_argument("--comment", required=True, help="Comment text")
    parser.add_argument("--author", default="cc", help="Comment author (default: cc)")
    args = parser.parse_args()

    board = load_board()
    card = find_card(board, args.plan)
    if not card:
        print(f"Error: No card with slug '{args.plan}'", file=sys.stderr)
        print("Available slugs:", ", ".join(c["slug"] for c in board["cards"]), file=sys.stderr)
        sys.exit(1)

    card, err = add_comment(board, args.plan, args.comment, args.author)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"Comment added to [{card['id']}] {card['title']}")
    print(f"  [{args.author}] {args.comment}")


if __name__ == "__main__":
    main()
