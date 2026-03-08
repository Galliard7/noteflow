#!/usr/bin/env python3
"""CLI to update a project phase status in Mission Control."""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_lib import load_board, find_project, update_phase


def main():
    parser = argparse.ArgumentParser(description="Update a project phase in Mission Control")
    parser.add_argument("--project", required=True, help="Project ID (e.g. 'dataflow')")
    parser.add_argument("--phase", required=True, help="Phase name (e.g. 'Profiling Pipeline')")
    parser.add_argument("--status", required=True, choices=["pending", "active", "done"],
                        help="New phase status")
    args = parser.parse_args()

    board = load_board()
    proj = find_project(board, args.project)
    if not proj:
        print(f"Error: No project '{args.project}'", file=sys.stderr)
        print("Available:", ", ".join(p["id"] for p in board["projects"]), file=sys.stderr)
        sys.exit(1)

    phases = proj.get("phases", [])
    if not phases:
        print(f"Error: Project '{args.project}' has no phases defined", file=sys.stderr)
        sys.exit(1)

    # Find phase by name (case-insensitive)
    phase_index = None
    for i, p in enumerate(phases):
        if p["name"].lower() == args.phase.lower():
            phase_index = i
            break

    if phase_index is None:
        print(f"Error: No phase '{args.phase}' in {args.project}", file=sys.stderr)
        print("Available phases:", ", ".join(p["name"] for p in phases), file=sys.stderr)
        sys.exit(1)

    proj, err = update_phase(board, args.project, phase_index, args.status)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    done = sum(1 for p in proj["phases"] if p["status"] == "done")
    total = len(proj["phases"])
    print(f"[{proj['name']}] {phases[phase_index]['name']} -> {args.status}")
    print(f"  Progress: {done}/{total} phases ({int(done/total*100)}%)")


if __name__ == "__main__":
    main()
