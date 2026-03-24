#!/usr/bin/env python3
"""NoteFlow Interactive Web Dashboard — HTTP server + REST API."""

import json
import os
import subprocess
import sys
from datetime import datetime
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/skill-backends/heartbeat"))
from nf_lib import (
    load_store, save_store, now_iso, format_id,
    find_item, update_item, add_subnote, delete_subnote,
    delete_item, reopen_item,
    get_columns, add_column, delete_column, reorder_columns,
    archive_done_items, load_archive,
)
from mc_lib import (
    load_board, save_board, find_card,
    add_card, update_card, delete_card, move_card,
    add_comment as mc_add_comment, update_comment as mc_update_comment, delete_comment as mc_delete_comment,
    find_project, add_project, update_project, update_phase, reorder_projects,
    add_decision, add_log_entry,
    add_status, delete_status, reorder_statuses,
    add_activity, list_activity, remove_activity, clear_all_activity,
)

HOST = "127.0.0.1"
PORT = 8765
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MC_HTML = os.path.join(SCRIPTS_DIR, "mission-control.html")
DASHBOARD_HTML = os.path.join(SCRIPTS_DIR, "dashboard.html")
STACK_FILE = os.path.expanduser("~/.openclaw/workspace/data/noteflow/stack.json")
LEARNING_PROFILE_FILE = os.path.expanduser("~/.openclaw/workspace/data/heartbeat/learning-profile.json")
LEARNING_CONCEPTS_FILE = os.path.expanduser("~/.openclaw/workspace/data/heartbeat/concepts.json")

LEARNING_CATEGORY_LABELS = {
    "system-design": "System Design",
    "ml-system-design": "ML System Design",
    "ml-fundamentals": "ML Fundamentals",
    "coding-patterns": "Coding Patterns",
    "sql-data": "SQL & Data",
}


def _load_learning_data():
    """Load learning profile + concepts and compute evaluation with SR data."""
    from importlib import import_module
    sr = import_module("spaced-repetition")

    try:
        with open(LEARNING_CONCEPTS_FILE) as f:
            concepts = json.load(f).get("concepts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        concepts = []

    try:
        with open(LEARNING_PROFILE_FILE) as f:
            profile = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        profile = {"ratings": {}, "category_weights": {}, "review_history": [], "study_stats": {}}

    ratings = profile.get("ratings", {})
    weights = profile.get("category_weights", {})
    review_history = profile.get("review_history", [])
    study_stats = profile.get("study_stats", {"daily_goal": 5, "study_log": {}})

    # Build concept lookup for related resolution
    concept_lookup = {c["id"]: c for c in concepts}

    # Group concepts by category
    cat_map = {}
    for c in concepts:
        cat = c.get("category", "system-design")
        cat_map.setdefault(cat, []).append(c)

    categories = []
    weighted_sum = 0.0
    weight_total = 0.0

    for cat_id in sorted(LEARNING_CATEGORY_LABELS.keys()):
        cat_concepts = cat_map.get(cat_id, [])
        total = len(cat_concepts)
        rated = []
        unrated = []

        for c in cat_concepts:
            r = ratings.get(c["id"])
            base = {"id": c["id"], "name": c["name"], "body": c.get("body", ""),
                    "tags": c.get("tags", []),
                    "examples": c.get("examples", []),
                    "difficulty": c.get("difficulty"),
                    "drills": c.get("drills", [])}

            # Resolve related concepts to {id, name, confidence}
            related_ids = c.get("related", [])
            resolved_related = []
            for rid in related_ids:
                rc = concept_lookup.get(rid)
                if rc:
                    rr = ratings.get(rid)
                    resolved_related.append({
                        "id": rid,
                        "name": rc["name"],
                        "confidence": rr["confidence"] if rr else None,
                    })
            base["related"] = resolved_related

            if r:
                migrated = sr.migrate_rating(r)
                mastery = sr.compute_mastery(migrated)
                base.update({
                    "confidence": r["confidence"],
                    "times_seen": r.get("times_seen", 1),
                    "notes": r.get("notes"),
                    "last_rated": r.get("last_rated"),
                    "mastery": mastery,
                    "next_review": migrated.get("next_review"),
                    "streak": migrated.get("streak", 0),
                    "ease_factor": migrated.get("ease_factor", 2.5),
                    "interval_days": migrated.get("interval_days", 0),
                })
                rated.append(base)
            else:
                base["related"] = resolved_related
                unrated.append(base)

        rated_count = len(rated)
        coverage = round(rated_count / total * 100, 1) if total > 0 else 0
        avg_conf = round(sum(r["confidence"] for r in rated) / rated_count, 2) if rated_count > 0 else 0

        w = weights.get(cat_id, 1.0)
        if rated_count > 0:
            weighted_sum += avg_conf * w
            weight_total += w

        categories.append({
            "id": cat_id,
            "label": LEARNING_CATEGORY_LABELS.get(cat_id, cat_id),
            "total": total, "rated": rated_count,
            "coverage_pct": coverage, "avg_confidence": avg_conf,
            "weight": w,
            "rated_concepts": sorted(rated, key=lambda x: x["confidence"]),
            "unrated_concepts": unrated,
        })

    readiness = round(weighted_sum / weight_total, 2) if weight_total > 0 else 0
    total_concepts = sum(c["total"] for c in categories)
    total_rated = sum(c["rated"] for c in categories)

    # Confidence distribution
    conf_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in ratings.values():
        c = r.get("confidence", 0)
        if c in conf_dist:
            conf_dist[c] += 1

    # Due concepts
    due_concepts = sr.get_due_concepts(profile, concepts)
    due_list = []
    for dc in due_concepts:
        r = dc.get("rating", {})
        due_list.append({
            "id": dc["id"],
            "name": dc["name"],
            "category": dc.get("category", "system-design"),
            "confidence": r.get("confidence", 0),
            "mastery": sr.compute_mastery(sr.migrate_rating(r)),
            "overdue_hours": dc.get("overdue_hours", 0),
        })

    # Study stats for today
    from datetime import timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_log = study_stats.get("study_log", {}).get(today_str, {"reviewed": 0, "new": 0})

    # Study streak: consecutive days with at least 1 review
    study_log = study_stats.get("study_log", {})
    study_streak = 0
    from datetime import timedelta
    check_date = datetime.now(timezone.utc).date()
    while True:
        ds = check_date.strftime("%Y-%m-%d")
        if study_log.get(ds, {}).get("reviewed", 0) > 0:
            study_streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    # Mastery distribution buckets
    mastery_dist = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    for r in ratings.values():
        m = sr.compute_mastery(sr.migrate_rating(r))
        if m < 25:
            mastery_dist["0-25"] += 1
        elif m < 50:
            mastery_dist["25-50"] += 1
        elif m < 75:
            mastery_dist["50-75"] += 1
        else:
            mastery_dist["75-100"] += 1

    return {
        "readiness_score": readiness,
        "total_concepts": total_concepts,
        "total_rated": total_rated,
        "categories": categories,
        "review_history": review_history,
        "confidence_distribution": conf_dist,
        "due_concepts": due_list,
        "study_stats": {
            "daily_goal": study_stats.get("daily_goal", 5),
            "today_reviewed": today_log.get("reviewed", 0),
            "today_new": today_log.get("new", 0),
            "study_streak": study_streak,
        },
        "mastery_distribution": mastery_dist,
    }


def _load_stack():
    """Load stack items from disk."""
    try:
        with open(STACK_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_stack(items):
    """Save stack items to disk (atomic write)."""
    os.makedirs(os.path.dirname(STACK_FILE), exist_ok=True)
    tmp = STACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STACK_FILE)


class DashboardHandler(BaseHTTPRequestHandler):
    """Handles REST API requests and serves the dashboard HTML."""

    def log_message(self, format, *args):
        """Suppress default request logging for cleaner output."""
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def _parse_path(self):
        """Parse URL path into segments."""
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        return parts

    def _parse_query(self):
        """Parse query string into dict."""
        parsed = urlparse(self.path)
        return {k: v[0] for k, v in parse_qs(parsed.query).items()}

    # --- Routing ---

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parts = self._parse_path()

        if not parts or parts == [""]:
            self._serve_html()
        elif parts == ["api", "items"]:
            self._api_list_items()
        elif parts == ["api", "columns"]:
            self._api_list_columns()
        elif parts == ["api", "reminders"]:
            self._api_list_reminders()
        elif parts == ["api", "cron", "jobs"]:
            self._api_list_cron_jobs()
        elif parts == ["api", "archive"]:
            self._api_list_archive()
        elif parts == ["api", "board"]:
            self._api_board_get()
        elif parts == ["api", "board", "activity"]:
            self._api_board_list_activity()
        elif (len(parts) == 5 and parts[:3] == ["api", "board", "projects"]
              and parts[4] == "graph"):
            self._api_board_project_graph(parts[3])
        elif parts == ["api", "files"]:
            self._api_read_file()
        elif parts == ["api", "stack"]:
            self._api_stack_list()
        elif parts == ["api", "vault", "daily"]:
            self._api_vault_daily()
        elif parts == ["api", "learning"]:
            self._api_learning()
        elif parts == ["api", "learning", "draw"]:
            self._api_learning_draw()
        else:
            self._send_error(404, "Not found")

    def do_POST(self):
        parts = self._parse_path()

        if parts == ["api", "items"]:
            self._api_add_item()
        elif parts == ["api", "columns"]:
            self._api_add_column()
        elif len(parts) == 4 and parts[:2] == ["api", "items"] and parts[3] == "done":
            self._api_mark_done(parts[2])
        elif len(parts) == 4 and parts[:2] == ["api", "items"] and parts[3] == "reopen":
            self._api_reopen(parts[2])
        elif len(parts) == 4 and parts[:2] == ["api", "items"] and parts[3] == "subnotes":
            self._api_add_subnote(parts[2])
        elif len(parts) == 4 and parts[:2] == ["api", "items"] and parts[3] == "cron":
            self._api_set_cron(parts[2])
        # Board API
        elif parts == ["api", "board", "cards"]:
            self._api_board_add_card()
        elif len(parts) == 5 and parts[:3] == ["api", "board", "cards"] and parts[4] == "comments":
            self._api_board_add_comment(parts[3])
        elif len(parts) == 5 and parts[:3] == ["api", "board", "cards"] and parts[4] == "move":
            self._api_board_move_card(parts[3])
        elif parts == ["api", "board", "statuses"]:
            self._api_board_add_status()
        elif parts == ["api", "board", "activity"]:
            self._api_board_add_activity()
        elif parts == ["api", "board", "projects"]:
            self._api_board_add_project()
        elif parts == ["api", "board", "decisions"]:
            self._api_board_add_decision()
        elif parts == ["api", "board", "log"]:
            self._api_board_add_log()
        elif parts == ["api", "stack"]:
            self._api_stack_add()
        elif parts == ["api", "learning", "rate"]:
            self._api_learning_rate()
        else:
            self._send_error(404, "Not found")

    def do_PUT(self):
        parts = self._parse_path()

        if len(parts) == 3 and parts[:2] == ["api", "items"]:
            self._api_update_item(parts[2])
        elif parts == ["api", "columns", "reorder"]:
            self._api_reorder_columns()
        elif len(parts) == 3 and parts[:2] == ["api", "columns"]:
            self._api_update_column(parts[2])
        elif parts == ["api", "board", "statuses", "reorder"]:
            self._api_board_reorder_statuses()
        elif len(parts) == 4 and parts[:3] == ["api", "board", "statuses"]:
            self._api_board_update_status(parts[3])
        elif parts == ["api", "board", "projects", "reorder"]:
            self._api_board_reorder_projects()
        elif len(parts) == 6 and parts[:3] == ["api", "board", "cards"] and parts[4] == "comments":
            self._api_board_update_comment(parts[3], parts[5])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "cards"]:
            self._api_board_update_card(parts[3])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "projects"]:
            self._api_board_update_project(parts[3])
        elif len(parts) == 6 and parts[:3] == ["api", "board", "projects"] and parts[4] == "phases":
            self._api_board_update_phase(parts[3], parts[5])
        elif parts == ["api", "stack"]:
            self._api_stack_replace()
        elif len(parts) == 3 and parts[:2] == ["api", "stack"]:
            self._api_stack_update(parts[2])
        else:
            self._send_error(404, "Not found")

    def do_DELETE(self):
        parts = self._parse_path()

        if len(parts) == 3 and parts[:2] == ["api", "items"]:
            self._api_delete_item(parts[2])
        elif len(parts) == 3 and parts[:2] == ["api", "columns"]:
            self._api_delete_column(parts[2])
        elif len(parts) == 5 and parts[:2] == ["api", "items"] and parts[3] == "subnotes":
            self._api_delete_subnote(parts[2], parts[4])
        elif len(parts) == 4 and parts[:2] == ["api", "items"] and parts[3] == "cron":
            self._api_cancel_cron(parts[2])
        elif len(parts) == 6 and parts[:3] == ["api", "board", "cards"] and parts[4] == "comments":
            self._api_board_delete_comment(parts[3], parts[5])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "cards"]:
            self._api_board_delete_card(parts[3])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "statuses"]:
            self._api_board_delete_status(parts[3])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "activity"]:
            self._api_board_delete_activity(parts[3])
        elif len(parts) == 3 and parts[:2] == ["api", "stack"]:
            self._api_stack_delete(parts[2])
        else:
            self._send_error(404, "Not found")

    # --- Serve HTML ---

    def _serve_html(self):
        # Serve mission-control.html if available, fallback to dashboard.html
        html_path = MC_HTML if os.path.exists(MC_HTML) else DASHBOARD_HTML
        try:
            with open(html_path, "r") as f:
                html = f.read().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        except FileNotFoundError:
            self._send_error(500, "HTML file not found")

    # --- API Handlers: Items ---

    def _api_list_items(self):
        store = load_store()
        archive_done_items(store)
        items = store.get("items", [])
        for item in items:
            item.setdefault("subnotes", [])
        self._send_json({"items": items})

    def _api_add_item(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        item_type = data.get("type", "task")
        title = data.get("title", "").strip()
        if not title:
            self._send_error(400, "Title is required")
            return

        store = load_store()
        item_id = format_id(store["next_id"])
        now = now_iso()

        item = {
            "id": item_id,
            "type": item_type,
            "status": "open",
            "title": title,
            "body": data.get("body", ""),
            "tags": data.get("tags", []),
            "created": now,
            "due": data.get("due") or None,
            "remind": data.get("remind") or None,
            "recurrence": data.get("recurrence") or None,
            "linked_cards": data.get("linked_cards") or [],
            "cron_installed": False,
            "snoozed_until": None,
            "subnotes": [],
            "history": [{"ts": now, "action": "created"}],
        }

        store["items"].append(item)
        store["next_id"] += 1
        save_store(store)

        self._send_json({"item": item}, 201)

    def _api_update_item(self, item_id):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        store = load_store()
        item, err = update_item(store, item_id, data)
        if err:
            self._send_error(404, err)
        else:
            item.setdefault("subnotes", [])
            self._send_json({"item": item})

    def _api_mark_done(self, item_id):
        store = load_store()
        item = find_item(store, item_id)
        if not item:
            self._send_error(404, f"Item {item_id} not found")
            return
        if item["status"] == "done":
            self._send_json({"item": item})
            return

        item["status"] = "done"
        item.setdefault("history", []).append({"ts": now_iso(), "action": "done"})
        save_store(store)
        item.setdefault("subnotes", [])
        self._send_json({"item": item})

    def _api_reopen(self, item_id):
        store = load_store()
        item, err = reopen_item(store, item_id)
        if err:
            self._send_error(400, err)
        else:
            item.setdefault("subnotes", [])
            self._send_json({"item": item})

    def _api_add_subnote(self, item_id):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        text = data.get("text", "").strip()
        if not text:
            self._send_error(400, "Comment text is required")
            return

        store = load_store()
        item, err = add_subnote(store, item_id, text)
        if err:
            self._send_error(404, err)
        else:
            self._send_json({"item": item})

    def _api_delete_subnote(self, item_id, index_str):
        try:
            index = int(index_str)
        except ValueError:
            self._send_error(400, "Invalid comment index")
            return

        store = load_store()
        item, err = delete_subnote(store, item_id, index)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"item": item})

    def _api_delete_item(self, item_id):
        store = load_store()
        item, err = delete_item(store, item_id)
        if err:
            self._send_error(404, err)
        else:
            item.setdefault("subnotes", [])
            self._send_json({"item": item})

    def _api_set_cron(self, item_id):
        """Install an OpenClaw cron job for a NoteFlow item via nf-remind.py."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            data = {}

        recurrence = data.get("recurrence") or None
        cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "nf-remind.py"), "--set", item_id]
        if recurrence:
            cmd += ["--recurrence", recurrence]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            store = load_store()
            item = find_item(store, item_id)
            if item:
                item.setdefault("subnotes", [])
                self._send_json({"item": item})
            else:
                self._send_json({"ok": True})
        else:
            err_msg = result.stderr.strip() or result.stdout.strip() or "Failed to set cron"
            self._send_error(500, err_msg)

    def _api_cancel_cron(self, item_id):
        """Remove an OpenClaw cron job for a NoteFlow item via nf-remind.py."""
        cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "nf-remind.py"), "--cancel", item_id]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            store = load_store()
            item = find_item(store, item_id)
            if item:
                item.setdefault("subnotes", [])
                self._send_json({"item": item})
            else:
                self._send_json({"ok": True})
        else:
            err_msg = result.stderr.strip() or result.stdout.strip() or "Failed to cancel cron"
            self._send_error(500, err_msg)

    def _api_list_reminders(self):
        store = load_store()
        reminders = [
            i for i in store.get("items", [])
            if i.get("cron_installed") or i.get("remind")
        ]
        for r in reminders:
            r.setdefault("subnotes", [])
        self._send_json({"reminders": reminders})

    def _api_list_archive(self):
        items = load_archive()
        for item in items:
            item.setdefault("subnotes", [])
        self._send_json({"items": items})

    def _load_cron_runs(self, job_id, limit=12):
        """Load recent run entries for a cron job from jsonl logs."""
        if not job_id:
            return []
        runs_path = os.path.join(self._CRON_RUNS_DIR, f"{job_id}.jsonl")
        if not os.path.exists(runs_path):
            return []

        rows = []
        try:
            with open(runs_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rows.append({
                        "ts": entry.get("ts"),
                        "action": entry.get("action"),
                        "status": entry.get("status"),
                        "summary": entry.get("summary", ""),
                        "runAtMs": entry.get("runAtMs"),
                        "durationMs": entry.get("durationMs"),
                        "deliveryStatus": entry.get("deliveryStatus"),
                        "nextRunAtMs": entry.get("nextRunAtMs"),
                    })
        except OSError:
            return []

        return rows[-limit:]

    def _api_list_cron_jobs(self):
        """Return OpenClaw cron jobs with recent run history for Mission Control."""
        if not os.path.exists(self._CRON_JOBS_FILE):
            self._send_json({"jobs": []})
            return

        try:
            with open(self._CRON_JOBS_FILE, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._send_json({"jobs": []})
            return

        jobs = []
        for raw in data.get("jobs", []):
            job_id = raw.get("id")
            runs = self._load_cron_runs(job_id)
            jobs.append({
                "id": job_id,
                "name": raw.get("name") or "(unnamed)",
                "enabled": bool(raw.get("enabled", True)),
                "createdAtMs": raw.get("createdAtMs"),
                "updatedAtMs": raw.get("updatedAtMs"),
                "schedule": raw.get("schedule") or {},
                "payload": raw.get("payload") or {},
                "delivery": raw.get("delivery") or {},
                "state": raw.get("state") or {},
                "runs": runs,
            })

        jobs.sort(key=lambda j: (j.get("state", {}).get("nextRunAtMs") or float("inf"), j.get("name", "")))
        self._send_json({"jobs": jobs, "generatedAt": datetime.now().isoformat()})

    # --- API Handlers: Columns ---

    def _api_list_columns(self):
        store = load_store()
        self._send_json({"columns": get_columns(store)})

    def _api_add_column(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        label = data.get("label", "").strip()
        if not label:
            self._send_error(400, "Column label is required")
            return

        col_id = data.get("id", label.lower().replace(" ", "-"))
        color = data.get("color", "#6366f1")
        icon = data.get("icon", "\uD83D\uDCCC")

        store = load_store()
        col, err = add_column(store, col_id, label, color, icon)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"column": col}, 201)

    def _api_delete_column(self, col_id):
        store = load_store()
        col, err = delete_column(store, col_id)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"column": col})

    def _api_reorder_columns(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        column_ids = data.get("order", [])
        if not column_ids:
            self._send_error(400, "Column order list is required")
            return

        store = load_store()
        err = reorder_columns(store, column_ids)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"columns": get_columns(store)})

    def _api_update_column(self, col_id):
        """Update a NoteFlow column's label, color, or icon."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        store = load_store()
        columns = store.get("columns", [])
        col = None
        for c in columns:
            if c["id"] == col_id:
                col = c
                break
        if not col:
            self._send_error(404, f"Column '{col_id}' not found")
            return

        if "label" in data:
            col["label"] = data["label"]
        if "color" in data:
            col["color"] = data["color"]
        if "icon" in data:
            col["icon"] = data["icon"]
        save_store(store)
        self._send_json(col)

    # --- API Handlers: Board (Mission Control) ---

    def _api_board_get(self):
        board = load_board()
        self._send_json(board)

    def _api_board_add_card(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        title = data.get("title", "").strip()
        if not title:
            self._send_error(400, "Title is required")
            return

        board = load_board()
        card = add_card(
            board,
            title=title,
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            project=data.get("project"),
            plan_file=data.get("plan_file"),
        )
        if data.get("phase"):
            card["phase"] = data["phase"]
            save_board(board)
        self._send_json({"card": card}, 201)

    def _api_board_update_card(self, slug):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        board = load_board()
        card, err = update_card(board, slug, data)
        if err:
            self._send_error(404, err)
        else:
            self._send_json({"card": card})

    def _api_board_delete_card(self, slug):
        board = load_board()
        card, err = delete_card(board, slug)
        if err:
            self._send_error(404, err)
        else:
            self._send_json({"card": card})

    def _api_board_add_comment(self, slug):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        text = data.get("text", "").strip()
        if not text:
            self._send_error(400, "Comment text is required")
            return

        author = data.get("author", "user")
        board = load_board()
        card, err = mc_add_comment(board, slug, text, author)
        if err:
            self._send_error(404, err)
        else:
            self._send_json({"card": card})

    def _api_board_update_comment(self, slug, index_str):
        try:
            index = int(index_str)
        except ValueError:
            self._send_error(400, "Invalid comment index")
            return
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        text = data.get("text", "").strip()
        if not text:
            self._send_error(400, "Comment text is required")
            return
        board = load_board()
        card, err = mc_update_comment(board, slug, index, text)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"card": card})

    def _api_board_delete_comment(self, slug, index_str):
        try:
            index = int(index_str)
        except ValueError:
            self._send_error(400, "Invalid comment index")
            return
        board = load_board()
        card, err = mc_delete_comment(board, slug, index)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"card": card})

    def _api_board_move_card(self, slug):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        status = data.get("status", "").strip()
        if not status:
            self._send_error(400, "Status is required")
            return

        board = load_board()
        card, err = move_card(board, slug, status)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"card": card})

    def _api_board_add_project(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        project_id = data.get("id", "").strip()
        name = data.get("name", "").strip()
        if not project_id or not name:
            self._send_error(400, "Project id and name are required")
            return

        board = load_board()
        proj, err = add_project(
            board, project_id, name,
            spec=data.get("spec"),
            code=data.get("code"),
            color=data.get("color", "#6366f1"),
        )
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"project": proj}, 201)

    def _api_board_update_project(self, project_id):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        board = load_board()
        proj, err = update_project(board, project_id, data)
        if err:
            self._send_error(404, err)
        else:
            self._send_json({"project": proj})

    def _api_board_add_decision(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        decision = data.get("decision", "").strip()
        if not decision:
            self._send_error(400, "Decision text is required")
            return

        board = load_board()
        entry = add_decision(board, decision, data.get("context", ""), data.get("date"))
        self._send_json({"decision": entry}, 201)

    def _api_board_add_log(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        text = data.get("text", "").strip()
        if not text:
            self._send_error(400, "Log text is required")
            return

        board = load_board()
        entry = add_log_entry(board, text)
        self._send_json({"log": entry}, 201)

    # --- API Handlers: Board Statuses ---

    def _api_board_add_status(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        label = data.get("label", "").strip()
        if not label:
            self._send_error(400, "Status label is required")
            return

        color = data.get("color", "#64748b")
        position = data.get("position")

        board = load_board()
        status_obj, err = add_status(board, label, color, position)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"status": status_obj}, 201)

    def _api_board_update_status(self, status_id):
        """Update a board status's label or color."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        board = load_board()
        found = None
        for s in board["statuses"]:
            if s["id"] == status_id:
                found = s
                break
        if not found:
            self._send_error(404, f"Status '{status_id}' not found")
            return

        if "label" in data:
            found["label"] = data["label"]
        if "color" in data:
            found["color"] = data["color"]
        save_board(board)
        self._send_json(found)

    def _api_board_delete_status(self, status_id):
        board = load_board()
        status_obj, err = delete_status(board, status_id)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"status": status_obj})

    def _api_board_reorder_statuses(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        order = data.get("order", [])
        if not order:
            self._send_error(400, "Status order list is required")
            return

        board = load_board()
        err = reorder_statuses(board, order)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"statuses": board["statuses"]})

    def _api_board_reorder_projects(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        order = data.get("order", [])
        if not order:
            self._send_error(400, "Project order list is required")
            return

        board = load_board()
        err = reorder_projects(board, order)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"projects": board["projects"]})

    # --- API Handlers: Board Activity ---

    def _api_board_list_activity(self):
        board = load_board()
        entries = list_activity(board)
        self._send_json({"activity": entries})

    def _api_board_add_activity(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        session = data.get("session", "").strip()
        text = data.get("text", "").strip()
        if not session or not text:
            self._send_error(400, "Session and text are required")
            return

        board = load_board()
        entry = add_activity(
            board, session, text,
            label=data.get("label"),
            color=data.get("color"),
        )
        self._send_json({"activity": entry}, 201)

    def _api_board_delete_activity(self, activity_id):
        board = load_board()
        entry, err = remove_activity(board, activity_id)
        if err:
            self._send_error(404, err)
        else:
            self._send_json({"activity": entry})

    def _api_board_update_phase(self, project_id, phase_index_str):
        try:
            phase_index = int(phase_index_str)
        except ValueError:
            self._send_error(400, "Invalid phase index")
            return

        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return

        new_status = data.get("status", "").strip()
        if not new_status:
            self._send_error(400, "Status is required")
            return

        board = load_board()
        proj, err = update_phase(board, project_id, phase_index, new_status)
        if err:
            self._send_error(400, err)
        else:
            self._send_json({"project": proj})

    # --- API Handlers: Project Graph ---

    def _api_board_project_graph(self, project_id):
        """Return graph data (nodes, edges, phases) for a project's roadmap view."""
        board = load_board()
        proj = find_project(board, project_id)
        if not proj:
            self._send_error(404, f"Project '{project_id}' not found")
            return

        # Build status color map
        status_colors = {}
        for s in board.get("statuses", []):
            status_colors[s["id"]] = s.get("color", "#64748b")
        fallback_colors = {"pending": "#f59e0b", "active": "#3b82f6", "done": "#10b981"}

        # Get project cards
        cards = [c for c in board.get("cards", []) if c.get("project") == project_id]

        # Build phase list from project
        phases = []
        for i, ph in enumerate(proj.get("phases", [])):
            phases.append({
                "name": ph["name"],
                "status": ph.get("status", "pending"),
                "index": i,
            })

        # Build nodes
        nodes = []
        for card in cards:
            sc = card.get("status", "pending")
            color = status_colors.get(sc) or fallback_colors.get(sc, "#64748b")
            nodes.append({
                "id": card["id"],
                "slug": card["slug"],
                "title": card["title"],
                "status": sc,
                "phase": card.get("phase", ""),
                "statusColor": color,
            })

        # Build edges from depends_on
        slug_to_id = {c["slug"]: c["id"] for c in cards}
        edges = []
        for card in cards:
            for dep_slug in card.get("depends_on", []):
                source_id = slug_to_id.get(dep_slug)
                if source_id:
                    edges.append({
                        "source": source_id,
                        "target": card["id"],
                    })

        self._send_json({"nodes": nodes, "edges": edges, "phases": phases})

    # --- API Handlers: File browsing ---

    _WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
    _CRON_ROOT = os.path.expanduser("~/.openclaw/cron")
    _CRON_RUNS_DIR = os.path.join(_CRON_ROOT, "runs")
    _CRON_JOBS_FILE = os.path.join(_CRON_ROOT, "jobs.json")
    _ALLOWED_ROOTS = [
        os.path.expanduser("~/.openclaw/workspace"),
        os.path.expanduser("~/skill-backends"),
        os.path.expanduser("~/.openclaw/vaults"),
    ]
    _VAULT_DAILY = os.path.expanduser("~/.openclaw/vaults/Claw/Daily")

    def _resolve_file_path(self, raw_path):
        """Resolve a project-relative path to an absolute path, with safety checks."""
        if raw_path.startswith("~/"):
            resolved = os.path.expanduser(raw_path)
        elif raw_path.startswith("workspace/"):
            resolved = os.path.join(self._WORKSPACE, raw_path[len("workspace/"):])
        else:
            resolved = os.path.join(self._WORKSPACE, raw_path)
        resolved = os.path.realpath(resolved)
        # Security: only allow paths under known roots
        for root in self._ALLOWED_ROOTS:
            if resolved.startswith(os.path.realpath(root)):
                return resolved
        return None

    def _api_read_file(self):
        query = self._parse_query()
        raw_path = query.get("path", "").strip()
        if not raw_path:
            self._send_error(400, "path parameter is required")
            return

        resolved = self._resolve_file_path(raw_path)
        if not resolved:
            self._send_error(403, "Path not allowed")
            return

        if not os.path.exists(resolved):
            self._send_error(404, f"Not found: {raw_path}")
            return

        if os.path.isdir(resolved):
            try:
                entries = []
                for name in sorted(os.listdir(resolved)):
                    if name.startswith("."):
                        continue
                    full = os.path.join(resolved, name)
                    entry_type = "directory" if os.path.isdir(full) else "file"
                    entries.append({"name": name, "type": entry_type})
                self._send_json({
                    "type": "directory",
                    "path": raw_path,
                    "name": os.path.basename(resolved),
                    "entries": entries,
                })
            except OSError as e:
                self._send_error(500, str(e))
        else:
            try:
                with open(resolved, "r", errors="replace") as f:
                    content = f.read(500_000)  # cap at 500KB
                self._send_json({
                    "type": "file",
                    "path": raw_path,
                    "name": os.path.basename(resolved),
                    "content": content,
                })
            except OSError as e:
                self._send_error(500, str(e))

    # --- API Handlers: Vault ---

    def _api_vault_daily(self):
        """List vault daily folders with file counts and file lists."""
        base = self._VAULT_DAILY
        if not os.path.isdir(base):
            self._send_json({"folders": []})
            return
        folders = []
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if not os.path.isdir(full) or name.startswith("."):
                continue
            files = []
            for fname in sorted(os.listdir(full)):
                if fname.startswith("."):
                    continue
                fpath = os.path.join(full, fname)
                if os.path.isfile(fpath):
                    files.append(fname)
            folders.append({"date": name, "files": files, "count": len(files)})
        self._send_json({"folders": folders})

    # --- API Handlers: Learning ---

    def _api_learning(self):
        self._send_json(_load_learning_data())

    def _api_learning_draw(self):
        """GET /api/learning/draw — draw an SR-weighted concept for study."""
        from importlib import import_module
        learn_draw = import_module("learn-draw")

        query = self._parse_query()
        category = query.get("category") or None

        try:
            with open(LEARNING_CONCEPTS_FILE) as f:
                concepts_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            concepts_data = {"concepts": []}

        if not concepts_data.get("concepts"):
            self._send_error(404, "No concepts found")
            return

        try:
            with open(LEARNING_PROFILE_FILE) as f:
                profile = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            profile = {"ratings": {}, "category_weights": {}}

        if category and category not in LEARNING_CATEGORY_LABELS:
            self._send_error(400, f"Unknown category: {category}")
            return

        concept = learn_draw.pick_concept(category, profile, concepts_data)
        if not concept:
            self._send_error(404, "No concepts available")
            return

        self._send_json({
            "id": concept["id"],
            "category": concept.get("category", "system-design"),
        })

    def _api_learning_rate(self):
        """POST /api/learning/rate — rate a concept with spaced repetition."""
        from importlib import import_module
        sr = import_module("spaced-repetition")

        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        concept_id = data.get("concept_id", "").strip()
        confidence = data.get("confidence")
        notes = data.get("notes")
        notes_only = data.get("notes_only", False)

        if not concept_id:
            self._send_error(400, "concept_id is required")
            return

        # Load profile
        try:
            with open(LEARNING_PROFILE_FILE) as f:
                profile = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            profile = {"ratings": {}, "category_weights": {}, "review_history": [], "study_stats": {}}

        ratings = profile.setdefault("ratings", {})

        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()

        # Notes-only update: append note without touching SR state
        if notes_only:
            if not notes:
                self._send_error(400, "notes is required with notes_only")
                return
            existing = ratings.get(concept_id)
            if not existing:
                self._send_error(400, f"concept '{concept_id}' has not been rated yet")
                return
            prev = existing.get("notes")
            if isinstance(prev, str):
                existing["notes"] = [{"text": prev, "ts": now}]
            elif not isinstance(prev, list):
                existing["notes"] = []
            existing["notes"].append({"text": notes, "ts": now})
            tmp = LEARNING_PROFILE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(profile, f, indent=2, default=str)
            os.replace(tmp, LEARNING_PROFILE_FILE)
            self._send_json({"ok": True, "concept_id": concept_id, "notes": existing["notes"]})
            return

        if not isinstance(confidence, int) or confidence < 1 or confidence > 5:
            self._send_error(400, "confidence must be 1-5")
            return

        existing = ratings.get(concept_id, {})
        is_new = concept_id not in ratings

        # Compute SR fields
        sr_fields = sr.compute_next_review(confidence, existing if existing else None)

        prev_notes = existing.get("notes")
        ratings[concept_id] = {
            "confidence": confidence,
            "last_rated": now,
            "times_seen": existing.get("times_seen", 0) + 1,
            **sr_fields,
        }
        if notes is not None:
            if isinstance(prev_notes, str):
                ratings[concept_id]["notes"] = [{"text": prev_notes, "ts": now}]
            elif isinstance(prev_notes, list):
                ratings[concept_id]["notes"] = list(prev_notes)
            else:
                ratings[concept_id]["notes"] = []
            ratings[concept_id]["notes"].append({"text": notes, "ts": now})
        elif prev_notes is not None:
            if isinstance(prev_notes, str):
                ratings[concept_id]["notes"] = [{"text": prev_notes, "ts": now}]
            else:
                ratings[concept_id]["notes"] = prev_notes

        profile.setdefault("review_history", []).append({
            "concept_id": concept_id,
            "rated_at": now,
            "confidence": confidence,
        })

        # Update study stats
        study_stats = profile.setdefault("study_stats", {"daily_goal": 5, "study_log": {}})
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_log = study_stats.setdefault("study_log", {}).setdefault(today_str, {"reviewed": 0, "new": 0})
        today_log["reviewed"] = today_log.get("reviewed", 0) + 1
        if is_new:
            today_log["new"] = today_log.get("new", 0) + 1

        # Atomic write
        tmp = LEARNING_PROFILE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(profile, f, indent=2, default=str)
        os.replace(tmp, LEARNING_PROFILE_FILE)

        self._send_json({"ok": True, "concept_id": concept_id, "confidence": confidence,
                         "next_review": sr_fields["next_review"], "mastery": sr.compute_mastery(ratings[concept_id])})

    # --- API Handlers: Stack ---

    def _api_stack_list(self):
        self._send_json({"items": _load_stack()})

    def _api_stack_add(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        title = data.get("title", "").strip()
        if not title:
            self._send_error(400, "Title is required")
            return
        import random, string
        item = {
            "id": "stk-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
            "title": title,
            "source": data.get("source", "custom"),
            "boardSlug": data.get("boardSlug") or None,
            "notes": list(data.get("notes", [])),
            "createdAt": datetime.utcnow().isoformat() + "Z",
        }
        items = _load_stack()
        items.insert(0, item)
        _save_stack(items)
        self._send_json({"item": item}, 201)

    def _api_stack_replace(self):
        """PUT /api/stack — replace entire stack (for reorder / bulk sync from frontend)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        items = data.get("items")
        if not isinstance(items, list):
            self._send_error(400, "items array is required")
            return
        _save_stack(items)
        self._send_json({"ok": True})

    def _api_stack_update(self, item_id):
        """PUT /api/stack/{id} — update a single stack item."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        items = _load_stack()
        target = None
        for it in items:
            if it.get("id") == item_id:
                target = it
                break
        if not target:
            self._send_error(404, "Stack item not found")
            return
        if "title" in data:
            target["title"] = data["title"]
        if "notes" in data:
            target["notes"] = list(data["notes"])
        if "boardSlug" in data:
            target["boardSlug"] = data["boardSlug"]
        if "source" in data:
            target["source"] = data["source"]
        _save_stack(items)
        self._send_json({"item": target})

    def _api_stack_delete(self, item_id):
        """DELETE /api/stack/{id} — remove a stack item."""
        items = _load_stack()
        new_items = [it for it in items if it.get("id") != item_id]
        if len(new_items) == len(items):
            self._send_error(404, "Stack item not found")
            return
        removed = [it for it in items if it.get("id") == item_id][0]
        _save_stack(new_items)
        self._send_json({"item": removed})


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mission Control Server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    server = HTTPServer((HOST, args.port), DashboardHandler)
    url = f"http://{HOST}:{args.port}"
    print(f"Mission Control running at {url}")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
