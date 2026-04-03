#!/usr/bin/env python3
"""NoteFlow: View and manage the Mission Control stack."""

import argparse
import json
import os
import random
import string
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_lib import load_board, find_card

STACK_FILE = os.path.expanduser("~/.openclaw/workspace/data/noteflow/stack.json")


def _load_stack():
    """Load stack data. Returns { lanes: [...], items: [...] }."""
    try:
        with open(STACK_FILE, "r") as f:
            data = json.load(f)
        # Migrate old flat-array format
        if isinstance(data, list):
            lanes = [{"id": "lane-1", "label": "Lane 1"}]
            for item in data:
                if isinstance(item, dict):
                    item.setdefault("lane", "lane-1")
            return {"lanes": lanes, "items": data}
        if isinstance(data, dict):
            data.setdefault("lanes", [{"id": "lane-1", "label": "Lane 1"}])
            data.setdefault("items", [])
            return data
        return {"lanes": [{"id": "lane-1", "label": "Lane 1"}], "items": []}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lanes": [{"id": "lane-1", "label": "Lane 1"}], "items": []}


def _save_stack(data):
    """Save stack data (lanes + items) to disk."""
    if isinstance(data, list):
        data = {"lanes": [{"id": "lane-1", "label": "Lane 1"}], "items": data}
    tmp = STACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STACK_FILE)


def _get_items():
    """Convenience: get just the items list."""
    return _load_stack()["items"]


def _save_items(items):
    """Convenience: save items while preserving lanes."""
    data = _load_stack()
    data["items"] = items
    _save_stack(data)


def _gen_id():
    chars = string.ascii_lowercase + string.digits
    return "stk-" + "".join(random.choices(chars, k=8))


def cmd_list(args):
    items = _get_items()
    if not items:
        print("Stack is empty.")
        return

    print(f"📋 Stack ({len(items)} items)\n")
    for i, item in enumerate(items):
        marker = "▶" if i == 0 else " "
        source_tag = f" [{item.get('boardSlug', '')}]" if item.get("source") == "board" else ""
        notes_tag = f" ({len(item.get('notes', []))} notes)" if item.get("notes") else ""
        print(f"  {marker} {i + 1}. {item['title']}{source_tag}{notes_tag}")


def cmd_add(args):
    items = _get_items()
    title = args.title

    # Check if it matches a board card slug
    board = load_board()
    card = find_card(board, title)

    if card:
        # It's a board slug — check for duplicates
        for item in items:
            if item.get("boardSlug") == card["slug"]:
                print(f"Already on stack: {card['title']}")
                return
        stack_data = _load_stack()
        first_lane = stack_data["lanes"][0]["id"] if stack_data["lanes"] else "lane-1"
        new_item = {
            "id": _gen_id(),
            "title": card["title"],
            "source": "board",
            "boardSlug": card["slug"],
            "notes": [],
            "lane": first_lane,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    else:
        # Custom item — check for exact title duplicate
        for item in items:
            if item["title"].lower() == title.lower():
                print(f"Already on stack: {item['title']}")
                return
        stack_data = _load_stack()
        first_lane = stack_data["lanes"][0]["id"] if stack_data["lanes"] else "lane-1"
        new_item = {
            "id": _gen_id(),
            "title": title,
            "source": "custom",
            "boardSlug": None,
            "notes": [],
            "lane": first_lane,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

    if args.top:
        items.insert(0, new_item)
    else:
        items.append(new_item)

    _save_items(items)
    pos = "top" if args.top else f"#{len(items)}"
    print(f"Added to stack ({pos}): {new_item['title']}")


def cmd_pop(args):
    items = _get_items()
    if not items:
        print("Stack is empty.")
        return
    popped = items.pop(0)
    _save_items(items)
    print(f"Popped: {popped['title']}")


def cmd_remove(args):
    items = _get_items()
    target = args.target.lower()

    match = None
    for item in items:
        if item["id"] == target or item["title"].lower() == target:
            match = item
            break
        if item.get("boardSlug") and item["boardSlug"].lower() == target:
            match = item
            break

    if not match:
        # Try partial title match
        candidates = [i for i in items if target in i["title"].lower()]
        if len(candidates) == 1:
            match = candidates[0]
        elif len(candidates) > 1:
            print(f"Multiple matches for '{args.target}':")
            for c in candidates:
                print(f"  - {c['title']} ({c['id']})")
            return
        else:
            print(f"Not found on stack: {args.target}")
            return

    items = [i for i in items if i["id"] != match["id"]]
    _save_items(items)
    print(f"Removed: {match['title']}")


def main():
    parser = argparse.ArgumentParser(description="Manage the Mission Control stack")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Show stack items")

    add_p = sub.add_parser("add", help="Add item to stack")
    add_p.add_argument("title", help="Item title or board card slug")
    add_p.add_argument("--top", action="store_true", help="Add to top of stack")

    sub.add_parser("pop", help="Remove top item")

    rm_p = sub.add_parser("remove", help="Remove specific item")
    rm_p.add_argument("target", help="Item ID, title, or board slug")

    args = parser.parse_args()

    if args.command == "list" or args.command is None:
        cmd_list(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "pop":
        cmd_pop(args)
    elif args.command == "remove":
        cmd_remove(args)


if __name__ == "__main__":
    main()
