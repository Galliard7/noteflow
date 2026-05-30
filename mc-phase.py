#!/usr/bin/env python3
"""CLI to manage project phases in Mission Control (add, remove, update status)."""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_lib import load_board, find_project, update_phase, add_phase, remove_phase


def cmd_add(args):
    board = load_board()
    proj = find_project(board, args.project)
    if not proj:
        print(f"Error: No project '{args.project}'", file=sys.stderr)
        print("Available:", ", ".join(p["id"] for p in board["projects"]), file=sys.stderr)
        sys.exit(1)

    proj, err = add_phase(board, args.project, args.name, args.description or "",
                          args.status or "pending", args.after)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    phases = proj["phases"]
    idx = next(i for i, p in enumerate(phases) if p["name"] == args.name)
    print(f"[{proj['name']}] Added phase: {args.name} ({args.status or 'pending'})")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"  Position: {idx + 1}/{len(phases)}")


def cmd_remove(args):
    board = load_board()
    proj = find_project(board, args.project)
    if not proj:
        print(f"Error: No project '{args.project}'", file=sys.stderr)
        print("Available:", ", ".join(p["id"] for p in board["projects"]), file=sys.stderr)
        sys.exit(1)

    proj, err = remove_phase(board, args.project, args.name)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"[{proj['name']}] Removed phase: {args.name}")
    print(f"  Remaining: {len(proj.get('phases', []))} phases")


def cmd_status(args):
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

    phase_index = None
    for i, p in enumerate(phases):
        if p["name"].lower() == args.phase.lower():
            phase_index = i
            break

    if phase_index is None:
        print(f"Error: No phase '{args.phase}' in {args.project}", file=sys.stderr)
        print("Available phases:", ", ".join(p["name"] for p in phases), file=sys.stderr)
        sys.exit(1)

    proj, err = update_phase(board, args.project, phase_index, args.set_status)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    done = sum(1 for p in proj["phases"] if p["status"] == "done")
    total = len(proj["phases"])
    print(f"[{proj['name']}] {phases[phase_index]['name']} -> {args.set_status}")
    print(f"  Progress: {done}/{total} phases ({int(done/total*100)}%)")


def cmd_list(args):
    board = load_board()
    proj = find_project(board, args.project)
    if not proj:
        print(f"Error: No project '{args.project}'", file=sys.stderr)
        print("Available:", ", ".join(p["id"] for p in board["projects"]), file=sys.stderr)
        sys.exit(1)

    phases = proj.get("phases", [])
    if not phases:
        print(f"[{proj['name']}] No phases defined")
        return

    icons = {"done": "✓", "active": "►", "pending": "○"}
    print(f"[{proj['name']}] {len(phases)} phases:")
    for i, p in enumerate(phases):
        icon = icons.get(p["status"], "?")
        print(f"  {i+1}. {icon} {p['name']} ({p['status']})")
        if p.get("description"):
            print(f"     {p['description']}")


def main():
    parser = argparse.ArgumentParser(description="Manage project phases in Mission Control")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a new phase to a project")
    p_add.add_argument("--project", required=True, help="Project ID")
    p_add.add_argument("--name", required=True, help="Phase name")
    p_add.add_argument("--description", help="Phase description")
    p_add.add_argument("--status", choices=["pending", "active", "done"], default="pending")
    p_add.add_argument("--after", help="Insert after this phase name (appends if omitted)")

    # remove
    p_rm = sub.add_parser("remove", help="Remove a phase from a project")
    p_rm.add_argument("--project", required=True, help="Project ID")
    p_rm.add_argument("--name", required=True, help="Phase name to remove")

    # status
    p_st = sub.add_parser("status", help="Update a phase's status")
    p_st.add_argument("--project", required=True, help="Project ID")
    p_st.add_argument("--phase", required=True, help="Phase name")
    p_st.add_argument("--set-status", required=True, choices=["pending", "active", "done"],
                       help="New phase status")

    # list
    p_ls = sub.add_parser("list", help="List all phases for a project")
    p_ls.add_argument("--project", required=True, help="Project ID")

    args = parser.parse_args()
    {"add": cmd_add, "remove": cmd_remove, "status": cmd_status, "list": cmd_list}[args.command](args)


if __name__ == "__main__":
    main()
