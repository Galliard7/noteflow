#!/usr/bin/env python3
"""NoteFlow: Manage reminders via OpenClaw cron scheduler (set, cancel, list)."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_lib import load_store, save_store, now_iso, TELEGRAM_CHAT_ID

JOB_PREFIX = "noteflow-"


def cron_job_name(item_id):
    """Generate OpenClaw cron job name from NoteFlow item ID."""
    return f"{JOB_PREFIX}{item_id}"


def build_cron_expr(remind_dt, recurrence):
    """Build a 5-field cron expression from remind datetime + recurrence pattern."""
    minute = remind_dt.minute
    hour = remind_dt.hour

    if recurrence == "daily":
        return f"{minute} {hour} * * *"
    elif recurrence == "weekdays":
        return f"{minute} {hour} * * 1-5"
    elif recurrence == "weekly":
        weekday = remind_dt.isoweekday() % 7  # cron: 0=Sun, 6=Sat
        return f"{minute} {hour} * * {weekday}"
    elif recurrence == "monthly":
        day = remind_dt.day
        return f"{minute} {hour} {day} * *"
    else:
        return None  # one-shot uses --at instead


def run_openclaw_cron(args_list):
    """Run an openclaw cron subcommand. Returns (success, output)."""
    cmd = ["openclaw", "cron"] + args_list
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def set_reminder(item_id, recurrence_override=None):
    """Install an OpenClaw cron job for a NoteFlow item."""
    store = load_store()

    target = None
    for item in store["items"]:
        if item["id"] == item_id:
            target = item
            break

    if not target:
        print(f"Error: Item {item_id} not found.")
        sys.exit(1)

    if not target.get("remind"):
        print(f"Error: Item {item_id} has no remind time set.")
        sys.exit(1)

    recurrence = recurrence_override or target.get("recurrence")
    remind_dt = datetime.fromisoformat(target["remind"])
    job_name = cron_job_name(item_id)
    message = f"Send this exact message to the user, nothing else: 🔔 [{item_id}] {target['title']}"

    # Remove existing job if any
    existing_uuid = find_job_id(item_id)
    if existing_uuid:
        run_openclaw_cron(["rm", existing_uuid])

    # Build cron add command
    cmd = [
        "add",
        "--name", job_name,
        "--announce",
        "--channel", "telegram",
        "--to", TELEGRAM_CHAT_ID,
        "--message", message,
        "--session", "isolated",
        "--light-context",
        "--exact",
        "--tz", "America/Chicago",
    ]

    if recurrence:
        cron_expr = build_cron_expr(remind_dt, recurrence)
        cmd.extend(["--cron", cron_expr])
    else:
        # One-shot: use --at with ISO datetime, auto-delete after run
        cmd.extend(["--at", target["remind"], "--delete-after-run"])

    success, stdout, stderr = run_openclaw_cron(cmd)

    if not success:
        print(f"Error creating cron job: {stderr}")
        sys.exit(1)

    # Update store
    target["recurrence"] = recurrence
    target["cron_installed"] = True
    target["history"].append({"ts": now_iso(), "action": f"cron set ({recurrence or 'one-shot'})"})
    save_store(store)

    schedule_desc = recurrence or "one-shot"
    time_str = remind_dt.strftime("%I:%M %p").lstrip("0")
    print(f"Reminder set ✓ [{item_id}] {target['title']}")
    print(f"  Schedule: {schedule_desc} at {time_str}")
    if recurrence:
        print(f"  Cron: {build_cron_expr(remind_dt, recurrence)}")


def find_job_id(item_id):
    """Look up the OpenClaw cron job UUID for a NoteFlow item."""
    job_name = cron_job_name(item_id)
    success, stdout, _ = run_openclaw_cron(["list", "--json"])
    if not success or not stdout:
        return None
    try:
        data = json.loads(stdout)
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        for job in jobs:
            if isinstance(job, dict) and job.get("name") == job_name:
                return job.get("id")
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def cancel_reminder(item_id):
    """Remove an OpenClaw cron job for a NoteFlow item."""
    job_uuid = find_job_id(item_id)

    if job_uuid:
        success, stdout, stderr = run_openclaw_cron(["rm", job_uuid])
        if success:
            print(f"Reminder cancelled ✓ [{item_id}]")
        else:
            print(f"Error cancelling cron job: {stderr}")
    else:
        print(f"No active cron job found for {item_id}.")

    # Update store
    store = load_store()
    for item in store["items"]:
        if item["id"] == item_id:
            item["cron_installed"] = False
            item["history"].append({"ts": now_iso(), "action": "cron cancelled"})
            break
    save_store(store)


def list_reminders():
    """List all active NoteFlow cron jobs."""
    success, stdout, stderr = run_openclaw_cron(["list", "--json"])

    if not success or not stdout:
        print("No active NoteFlow reminders.")
        return

    try:
        data = json.loads(stdout)
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
    except json.JSONDecodeError:
        print("No active NoteFlow reminders.")
        return

    if not isinstance(jobs, list):
        print("No active NoteFlow reminders.")
        return

    nf_jobs = [j for j in jobs if isinstance(j, dict) and j.get("name", "").startswith(JOB_PREFIX)]

    if not nf_jobs:
        print("No active NoteFlow reminders.")
        return

    print("Active NoteFlow reminders:")
    for job in nf_jobs:
        name = job.get("name", "")
        item_id = name[len(JOB_PREFIX):]
        schedule = job.get("schedule", {})
        if schedule.get("kind") == "cron":
            sched_str = schedule.get("expr", "?")
        elif schedule.get("kind") == "at":
            sched_str = f"once at {schedule.get('at', '?')}"
        else:
            sched_str = "?"
        enabled = "active" if job.get("enabled", True) else "disabled"
        print(f"  [{item_id}] {sched_str} ({enabled})")


def main():
    parser = argparse.ArgumentParser(description="Manage NoteFlow cron reminders")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--set", metavar="ID", help="Install cron job for item ID")
    group.add_argument("--cancel", metavar="ID", help="Remove cron job for item ID")
    group.add_argument("--list", action="store_true", help="List active cron reminders")

    parser.add_argument(
        "--recurrence",
        choices=["daily", "weekdays", "weekly", "monthly"],
        default=None,
        help="Recurrence pattern (omit for one-shot)",
    )
    args = parser.parse_args()

    if args.set:
        set_reminder(args.set, args.recurrence)
    elif args.cancel:
        cancel_reminder(args.cancel)
    elif args.list:
        list_reminders()


if __name__ == "__main__":
    main()
