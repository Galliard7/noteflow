#!/usr/bin/env python3
"""NoteFlow: Remove the last added item (undo recent capture)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store, save_store


def main():
    store = load_store()

    if not store["items"]:
        print("Nothing to undo — no items exist.")
        sys.exit(0)

    # Find the most recently created item (last in list)
    removed = store["items"].pop()
    save_store(store)

    print(f"Removed → [{removed['id']}] {removed['title']}")


if __name__ == "__main__":
    main()
