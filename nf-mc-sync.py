#!/usr/bin/env python3
"""NoteFlow → Mission Control sync: ensure every NoteFlow task has a linked MC card."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store, save_store, find_item, now_iso
from mc_lib import load_board, save_board, add_card, find_card, move_card


def sync_tasks():
    """Find open NoteFlow tasks without linked MC cards, create cards, link them.
    Also sync done status bidirectionally."""
    store = load_store()
    board = load_board()

    created = []
    synced_done = []

    # --- Forward sync: NoteFlow tasks → MC cards ---
    for item in store["items"]:
        if item["type"] != "task":
            continue
        if item.get("linked_cards"):
            continue  # already linked to at least one card
        if item["status"] == "done":
            continue  # don't create cards for already-done tasks

        # Create an MC card for this task
        card = add_card(
            board,
            title=item["title"],
            description=item.get("body", ""),
            status="pending",
            project=None,
            plan_file=None,
        )

        # Link the NoteFlow item back to the card
        item.setdefault("linked_cards", []).append(card["slug"])
        item.setdefault("history", []).append(
            {"ts": now_iso(), "action": f"linked to MC card {card['slug']}"}
        )

        created.append({"nf_id": item["id"], "nf_title": item["title"], "mc_slug": card["slug"], "mc_id": card["id"]})

        # Reload board after each add_card (it saves internally)
        board = load_board()

    # --- Bidirectional done sync ---
    for item in store["items"]:
        if item["type"] != "task":
            continue
        slugs = item.get("linked_cards", [])
        if not slugs:
            continue

        for slug in slugs:
            card = find_card(board, slug)
            if not card:
                continue

            # NoteFlow done → MC card done
            if item["status"] == "done" and card["status"] != "done":
                move_card(board, slug, "done")
                board = load_board()
                synced_done.append({"direction": "nf→mc", "nf_id": item["id"], "mc_slug": slug})

            # MC card done → NoteFlow done (only if ALL linked cards are done)
            elif card["status"] == "done" and item["status"] == "open":
                all_done = all(
                    (find_card(board, s) or {}).get("status") == "done"
                    for s in slugs
                )
                if all_done:
                    item["status"] = "done"
                    item.setdefault("history", []).append(
                        {"ts": now_iso(), "action": "done (synced from MC cards)"}
                    )
                    synced_done.append({"direction": "mc→nf", "nf_id": item["id"], "mc_slug": slug})
                    break  # already marked done, stop checking this item's cards

    # Save NoteFlow store (links + done syncs)
    if created or synced_done:
        save_store(store)

    # --- Report ---
    if not created and not synced_done:
        print("nf-mc-sync: all NoteFlow tasks already linked. No changes.")
        return

    if created:
        print(f"nf-mc-sync: created {len(created)} MC card(s):")
        for c in created:
            print(f"  [{c['nf_id']}] {c['nf_title']} → {c['mc_id']} ({c['mc_slug']})")

    if synced_done:
        print(f"nf-mc-sync: synced {len(synced_done)} done status(es):")
        for s in synced_done:
            print(f"  {s['direction']}: {s['nf_id']} ↔ {s['mc_slug']}")


if __name__ == "__main__":
    sync_tasks()
