#!/usr/bin/env python3
"""Add or delete a subnote on a NoteFlow entry."""

import argparse
import sys
from nf_lib import load_store, add_subnote, delete_subnote


def main():
    parser = argparse.ArgumentParser(description="Manage subnotes on a NoteFlow entry")
    parser.add_argument("--id", required=True, help="Item ID (e.g. nf-002)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", metavar="TEXT", help="Add a subnote with this text")
    group.add_argument("--delete", metavar="INDEX", type=int, help="Delete subnote at this index")
    args = parser.parse_args()

    store = load_store()

    if args.add:
        item, err = add_subnote(store, args.id, args.add)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)
        count = len(item.get("subnotes", []))
        print(f"Subnote added → [{item['id']}] {item['title']}")
        print(f"  \"{args.add}\"")
        print(f"  ({count} subnote{'s' if count != 1 else ''} total)")

    elif args.delete is not None:
        item, err = delete_subnote(store, args.id, args.delete)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)
        count = len(item.get("subnotes", []))
        print(f"Subnote removed → [{item['id']}] {item['title']}")
        print(f"  ({count} subnote{'s' if count != 1 else ''} remaining)")


if __name__ == "__main__":
    main()
