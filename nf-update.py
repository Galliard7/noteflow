#!/usr/bin/env python3
"""Update fields on a NoteFlow entry."""

import argparse
import sys
from nf_lib import load_store, update_item, find_item


def main():
    parser = argparse.ArgumentParser(description="Update a NoteFlow entry")
    parser.add_argument("--id", required=True, help="Item ID (e.g. nf-002)")
    parser.add_argument("--title", help="New title")
    parser.add_argument("--body", help="New body text")
    parser.add_argument("--type", help="New type (task, idea, note, reminder)")
    parser.add_argument("--due", help="New due date (ISO 8601) or 'clear' to remove")
    parser.add_argument("--remind", help="New remind date (ISO 8601) or 'clear' to remove")
    parser.add_argument("--recurrence", help="New recurrence (daily|weekdays|weekly|monthly) or 'clear'")
    parser.add_argument("--add-tags", nargs="+", metavar="TAG", help="Tags to add")
    parser.add_argument("--remove-tags", nargs="+", metavar="TAG", help="Tags to remove")
    parser.add_argument("--add-refs", nargs="+", metavar="REF", help="References to add (URLs, file paths, etc.)")
    parser.add_argument("--remove-refs", nargs="+", metavar="REF", help="References to remove")
    parser.add_argument("--project", help="Project ID to associate, or 'clear' to remove")
    args = parser.parse_args()

    # Must have at least one update
    has_update = any([
        args.title, args.body, args.type, args.due, args.remind,
        args.recurrence, args.add_tags, args.remove_tags,
        args.add_refs, args.remove_refs, args.project,
    ])
    if not has_update:
        parser.error("at least one update flag is required")

    store = load_store()
    item = find_item(store, args.id)
    if not item:
        print(f"Error: {args.id} not found", file=sys.stderr)
        sys.exit(1)

    updates = {}

    if args.title:
        updates["title"] = args.title
    if args.body:
        updates["body"] = args.body
    if args.type:
        updates["type"] = args.type

    # Handle 'clear' for date fields
    if args.due:
        updates["due"] = None if args.due == "clear" else args.due
    if args.remind:
        updates["remind"] = None if args.remind == "clear" else args.remind
    if args.recurrence:
        updates["recurrence"] = None if args.recurrence == "clear" else args.recurrence

    # Merge tags
    if args.add_tags or args.remove_tags:
        current_tags = list(item.get("tags", []))
        if args.add_tags:
            for t in args.add_tags:
                if t not in current_tags:
                    current_tags.append(t)
        if args.remove_tags:
            current_tags = [t for t in current_tags if t not in args.remove_tags]
        updates["tags"] = current_tags

    # Project
    if args.project:
        updates["project"] = None if args.project == "clear" else args.project

    # Merge references
    if args.add_refs or args.remove_refs:
        current_refs = list(item.get("references", []))
        if args.add_refs:
            for r in args.add_refs:
                if r not in current_refs:
                    current_refs.append(r)
        if args.remove_refs:
            current_refs = [r for r in current_refs if r not in args.remove_refs]
        updates["references"] = current_refs

    item, err = update_item(store, args.id, updates)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Show result
    changed = list(updates.keys())
    print(f"Updated → [{item['id']}] {item['title']}")
    print(f"  Changed: {', '.join(changed)}")

    # Show current values for changed fields
    for key in changed:
        val = item.get(key)
        if key == "tags":
            print(f"  Tags: {', '.join(val) if val else '(none)'}")
        elif key == "references":
            print(f"  References: {len(val)} item{'s' if len(val) != 1 else ''}")
            for r in val:
                print(f"    → {r}")
        elif val is None:
            print(f"  {key.capitalize()}: (cleared)")
        else:
            print(f"  {key.capitalize()}: {val}")


if __name__ == "__main__":
    main()
