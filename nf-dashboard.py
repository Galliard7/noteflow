#!/usr/bin/env python3
"""NoteFlow Interactive Web Dashboard — HTTP server + REST API."""

import json
import os
import subprocess
import sys
from datetime import datetime
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/skill-backends/heartbeat"))
sys.path.insert(0, os.path.expanduser("~/skill-backends/neetcode"))
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

NEETCODE_PROFILE_FILE = os.path.expanduser("~/.openclaw/workspace/data/neetcode/neetcode-profile.json")
NEETCODE_PROBLEMS_FILE = os.path.expanduser("~/.openclaw/workspace/data/neetcode/problems.json")

NEETCODE_TOPIC_LABELS = {
    "arrays-hashing": "Arrays & Hashing",
    "two-pointers": "Two Pointers",
    "stack": "Stack",
    "binary-search": "Binary Search",
    "sliding-window": "Sliding Window",
    "linked-list": "Linked List",
    "trees": "Trees",
    "tries": "Tries",
    "heap-priority-queue": "Heap / Priority Queue",
    "backtracking": "Backtracking",
    "graphs": "Graphs",
    "advanced-graphs": "Advanced Graphs",
    "1d-dp": "1-D Dynamic Programming",
    "2d-dp": "2-D Dynamic Programming",
    "greedy": "Greedy",
    "intervals": "Intervals",
    "math-geometry": "Math & Geometry",
    "bit-manipulation": "Bit Manipulation",
}

NEETCODE_DIFFICULTY_COLORS = {"easy": "#22c55e", "medium": "#eab308", "hard": "#ef4444"}


def _evaluate_neetcode_mode(problems, profile, mode):
    """Evaluate one mode's NeetCode state — returns per-topic + aggregates."""
    from importlib import import_module
    import profile_io
    sr = import_module("spaced-repetition")

    mode_state = profile_io.get_mode_state(profile, mode)
    ratings = mode_state["ratings"]
    review_history = mode_state["review_history"]
    study_stats = profile.get("study_stats", {"daily_goal": 3, "study_log": {}})

    # Build problem lookup
    problem_lookup = {p["id"]: p for p in problems}

    # Group by topic
    topic_map = {}
    for p in problems:
        t = p.get("topic", "arrays-hashing")
        topic_map.setdefault(t, []).append(p)

    topics = []
    weighted_sum = 0.0
    weight_total = 0.0

    for topic_id in sorted(NEETCODE_TOPIC_LABELS.keys()):
        topic_problems = topic_map.get(topic_id, [])
        total = len(topic_problems)
        rated = []
        unrated = []

        for p in topic_problems:
            r = ratings.get(p["id"])
            base = {
                "id": p["id"], "name": p["name"], "number": p.get("number"),
                "difficulty": p.get("difficulty", "medium"),
                "url": p.get("url", ""),
                "youtube_url": p.get("youtube_url", ""),
                "statement": p.get("statement", ""),
                "approaches": p.get("approaches", []),
                "patterns": p.get("patterns", []),
                "key_insight": p.get("key_insight", ""),
            }

            # Resolve related problems
            related_ids = p.get("related", [])
            resolved_related = []
            for rid in related_ids:
                rp = problem_lookup.get(rid)
                if rp:
                    rr = ratings.get(rid)
                    resolved_related.append({
                        "id": rid, "name": rp["name"],
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
                unrated.append(base)

        rated_count = len(rated)
        coverage = round(rated_count / total * 100, 1) if total > 0 else 0
        avg_conf = round(sum(r["confidence"] for r in rated) / rated_count, 2) if rated_count > 0 else 0

        if rated_count > 0:
            weighted_sum += avg_conf
            weight_total += 1

        # Difficulty distribution
        diff_dist = {"easy": {"total": 0, "solved": 0}, "medium": {"total": 0, "solved": 0}, "hard": {"total": 0, "solved": 0}}
        for p in topic_problems:
            d = p.get("difficulty", "medium")
            diff_dist[d]["total"] += 1
            if p["id"] in ratings:
                diff_dist[d]["solved"] += 1

        topics.append({
            "id": topic_id,
            "label": NEETCODE_TOPIC_LABELS.get(topic_id, topic_id),
            "total": total, "rated": rated_count,
            "coverage_pct": coverage, "avg_confidence": avg_conf,
            "difficulty_distribution": diff_dist,
            "rated_problems": sorted(rated, key=lambda x: x["confidence"]),
            "unrated_problems": unrated,
        })

    readiness = round(weighted_sum / weight_total, 2) if weight_total > 0 else 0
    total_problems = sum(t["total"] for t in topics)
    total_rated = sum(t["rated"] for t in topics)

    # Confidence distribution
    conf_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in ratings.values():
        c = r.get("confidence", 0)
        if c in conf_dist:
            conf_dist[c] += 1

    # Difficulty solved counts
    diff_solved = {"easy": 0, "medium": 0, "hard": 0}
    for p in problems:
        if p["id"] in ratings:
            d = p.get("difficulty", "medium")
            diff_solved[d] = diff_solved.get(d, 0) + 1

    # Due problems
    due_problems = sr.get_due_concepts(profile, problems)
    due_list = []
    for dp in due_problems:
        r = dp.get("rating", {})
        due_list.append({
            "id": dp["id"], "name": dp["name"],
            "topic": dp.get("topic", "arrays-hashing"),
            "difficulty": dp.get("difficulty", "medium"),
            "confidence": r.get("confidence", 0),
            "mastery": sr.compute_mastery(sr.migrate_rating(r)),
            "overdue_hours": dp.get("overdue_hours", 0),
        })

    # Study stats for today
    from datetime import timezone as tz, timedelta
    today_str = datetime.now(tz.utc).strftime("%Y-%m-%d")
    today_log = study_stats.get("study_log", {}).get(today_str, {"reviewed": 0, "new": 0})

    # Study streak
    study_log = study_stats.get("study_log", {})
    study_streak = 0
    check_date = datetime.now(tz.utc).date()
    while True:
        ds = check_date.strftime("%Y-%m-%d")
        if study_log.get(ds, {}).get("reviewed", 0) > 0:
            study_streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return {
        "readiness_score": readiness,
        "total_problems": total_problems,
        "total_rated": total_rated,
        "topics": topics,
        "review_history": review_history,
        "confidence_distribution": conf_dist,
        "difficulty_solved": diff_solved,
        "due_problems": due_list,
        "study_stats": {
            "daily_goal": study_stats.get("daily_goal", 3),
            "today_reviewed": today_log.get("reviewed", 0),
            "today_new": today_log.get("new", 0),
            "study_streak": study_streak,
        },
    }


def _load_neetcode_data():
    """Load NeetCode profile + problems and compute per-mode evaluations."""
    import profile_io

    try:
        with open(NEETCODE_PROBLEMS_FILE) as f:
            problems = json.load(f).get("problems", [])
    except (FileNotFoundError, json.JSONDecodeError):
        problems = []

    profile = profile_io.load_profile()
    current_mode = profile_io.resolve_mode(profile)

    study_eval = _evaluate_neetcode_mode(problems, profile, "study")
    solve_eval = _evaluate_neetcode_mode(problems, profile, "solve")

    return {
        "modes": {"study": study_eval, "solve": solve_eval},
        "current_mode": current_mode,
    }


GUIDED_TOPIC_ORDER = [
    "arrays-hashing", "two-pointers", "stack", "binary-search",
    "sliding-window", "linked-list", "trees", "tries",
    "heap-priority-queue", "backtracking", "graphs", "advanced-graphs",
    "1d-dp", "2d-dp", "greedy", "intervals", "math-geometry", "bit-manipulation",
]

GUIDED_UNLOCK_THRESHOLD = 0.75
GUIDED_WINDOW_SIZE = 3


def _sort_by_topic(problems):
    """Group problems by topic and sort each: easy → medium → hard, then by name."""
    diff_order = {"easy": 0, "medium": 1, "hard": 2}
    by_topic = {}
    for p in problems:
        t = p.get("topic", "arrays-hashing")
        by_topic.setdefault(t, []).append(p)
    for t in by_topic:
        by_topic[t].sort(key=lambda p: (diff_order.get(p.get("difficulty", "medium"), 1), p.get("name", "")))
    return by_topic


def _build_guided_ordering(problems):
    """Return the flat deterministic guided-track ordering.

    Structure::
        [
          {"topic": "arrays-hashing", "label": "Arrays & Hashing", "problems": [
            {"id", "name", "difficulty", "number", "index_global", "index_topic"}
          ]},
          ...
        ]
    """
    by_topic = _sort_by_topic(problems)
    ordering = []
    global_idx = 0
    for topic_id in GUIDED_TOPIC_ORDER:
        topic_problems = by_topic.get(topic_id, [])
        entries = []
        for topic_idx, p in enumerate(topic_problems):
            entries.append({
                "id": p["id"],
                "name": p["name"],
                "difficulty": p.get("difficulty", "medium"),
                "number": p.get("number"),
                "index_global": global_idx,
                "index_topic": topic_idx,
            })
            global_idx += 1
        ordering.append({
            "topic": topic_id,
            "label": NEETCODE_TOPIC_LABELS.get(topic_id, topic_id),
            "problems": entries,
        })
    return ordering


def _compute_guided_track(mode=None):
    """Compute guided track state for a given mode (defaults to profile.current_mode)."""
    import profile_io

    try:
        with open(NEETCODE_PROBLEMS_FILE) as f:
            problems = json.load(f).get("problems", [])
    except (FileNotFoundError, json.JSONDecodeError):
        problems = []

    profile = profile_io.load_profile()
    resolved = profile_io.resolve_mode(profile, mode)
    mode_state = profile_io.get_mode_state(profile, resolved)
    ratings = mode_state["ratings"]
    review_history = mode_state["review_history"]

    by_topic = _sort_by_topic(problems)

    # Completion per topic
    topic_completion = {}
    for t in GUIDED_TOPIC_ORDER:
        tp = by_topic.get(t, [])
        total = len(tp)
        rated = sum(1 for p in tp if p["id"] in ratings)
        topic_completion[t] = rated / total if total > 0 else 1.0

    # Determine unlocked topics (sequential gate)
    unlocked = []
    for i, t in enumerate(GUIDED_TOPIC_ORDER):
        if i == 0:
            unlocked.append(t)
        elif topic_completion[GUIDED_TOPIC_ORDER[i - 1]] >= GUIDED_UNLOCK_THRESHOLD:
            unlocked.append(t)
        else:
            break

    active = [t for t in unlocked if topic_completion[t] < 1.0][:GUIDED_WINDOW_SIZE]

    last_topic_time = {}
    for entry in review_history:
        pid = entry.get("problem_id", "")
        for p in problems:
            if p["id"] == pid:
                last_topic_time[p.get("topic")] = entry.get("rated_at", "")
                break

    interleaved = sorted(active, key=lambda t: last_topic_time.get(t, ""))

    next_problem = None
    for t in interleaved:
        for p in by_topic.get(t, []):
            if p["id"] not in ratings:
                next_problem = {
                    "id": p["id"],
                    "name": p["name"],
                    "topic": t,
                    "difficulty": p.get("difficulty", "medium"),
                    "number": p.get("number"),
                }
                break
        if next_problem:
            break

    total_rated = sum(1 for p in problems if p["id"] in ratings)
    total_problems = len(problems)

    next_unlock = None
    unlock_gate_topic = None
    next_unlock_pct = 0
    if len(unlocked) < len(GUIDED_TOPIC_ORDER):
        next_unlock = GUIDED_TOPIC_ORDER[len(unlocked)]
        unlock_gate_topic = GUIDED_TOPIC_ORDER[len(unlocked) - 1]
        next_unlock_pct = round(topic_completion[unlock_gate_topic] * 100)

    return {
        "mode": resolved,
        "current_mode": profile.get("current_mode", "solve"),
        "active_topics": active,
        "unlocked_topics": unlocked,
        "topic_completion": {t: round(topic_completion[t] * 100) for t in GUIDED_TOPIC_ORDER},
        "overall_progress": round(total_rated / total_problems * 100) if total_problems else 0,
        "total_rated": total_rated,
        "total_problems": total_problems,
        "next_problem": next_problem,
        "next_unlock": next_unlock,
        "unlock_gate_topic": unlock_gate_topic,
        "next_unlock_pct": next_unlock_pct,
        "all_done": next_problem is None and total_rated >= total_problems,
    }


def _compute_guided_cursors(problems, profile):
    """For each mode, return the index_global of the first unrated problem."""
    import profile_io
    ordering = _build_guided_ordering(problems)
    flat = [p for topic in ordering for p in topic["problems"]]
    cursors = {}
    for m in ("study", "solve"):
        ratings = profile_io.get_mode_state(profile, m)["ratings"]
        cursor = len(flat)
        next_pid = None
        for entry in flat:
            if entry["id"] not in ratings:
                cursor = entry["index_global"]
                next_pid = entry["id"]
                break
        cursors[m] = {"index_global": cursor, "next_problem_id": next_pid}
    return cursors


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
    """Load stack data from disk. Returns { lanes: [...], items: [...] }."""
    try:
        with open(STACK_FILE, "r") as f:
            data = json.load(f)
        # Migrate old flat-array format to new lanes format
        if isinstance(data, list):
            lanes = [{"id": "lane-1", "label": "Lane 1"}]
            items = []
            for item in data:
                if isinstance(item, dict):
                    item.setdefault("lane", "lane-1")
                    items.append(item)
            return {"lanes": lanes, "items": items}
        if isinstance(data, dict):
            data.setdefault("lanes", [{"id": "lane-1", "label": "Lane 1"}])
            data.setdefault("items", [])
            return data
        return {"lanes": [{"id": "lane-1", "label": "Lane 1"}], "items": []}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lanes": [{"id": "lane-1", "label": "Lane 1"}], "items": []}


def _save_stack(data):
    """Save stack data to disk (atomic write). Accepts { lanes, items } or bare items list."""
    os.makedirs(os.path.dirname(STACK_FILE), exist_ok=True)
    # Normalize: if caller passes a bare list, wrap it
    if isinstance(data, list):
        data = {"lanes": [{"id": "lane-1", "label": "Lane 1"}], "items": data}
    tmp = STACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STACK_FILE)


class DashboardHandler(BaseHTTPRequestHandler):
    """Handles REST API requests and serves the dashboard HTML."""

    timeout = 30            # socket-level timeout — drops idle connections
    protocol_version = "HTTP/1.0"  # disable keep-alive — one request per connection

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
        try:
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
            elif parts == ["api", "neetcode"]:
                self._api_neetcode()
            elif parts == ["api", "neetcode", "draw"]:
                self._api_neetcode_draw()
            elif parts == ["api", "neetcode", "guided"]:
                self._api_neetcode_guided()
            elif parts == ["api", "neetcode", "guided", "ordering"]:
                self._api_neetcode_guided_ordering()
            else:
                self._send_error(404, "Not found")
        except Exception as e:
            try:
                self._send_error(500, f"Internal error: {e}")
            except Exception:
                pass

    def do_POST(self):
        try:
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
            elif parts == ["api", "neetcode", "rate"]:
                self._api_neetcode_rate()
            elif parts == ["api", "neetcode", "mode"]:
                self._api_neetcode_set_mode()
            else:
                self._send_error(404, "Not found")
        except Exception as e:
            try:
                self._send_error(500, f"Internal error: {e}")
            except Exception:
                pass

    def do_PUT(self):
        try:
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
        except Exception as e:
            try:
                self._send_error(500, f"Internal error: {e}")
            except Exception:
                pass

    def do_DELETE(self):
        try:
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
        except Exception as e:
            try:
                self._send_error(500, f"Internal error: {e}")
            except Exception:
                pass

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

    # --- API Handlers: NeetCode ---

    def _api_neetcode(self):
        self._send_json(_load_neetcode_data())

    def _api_neetcode_draw(self):
        """GET /api/neetcode/draw — draw an SR-weighted problem for study."""
        from importlib import import_module
        import profile_io
        nc_draw = import_module("nc-draw")

        query = self._parse_query()
        topics_str = query.get("topics") or None
        difficulty = query.get("difficulty") or None
        blind = query.get("blind", "").lower() in ("true", "1", "yes")
        mode_arg = query.get("mode") or None
        if mode_arg and mode_arg not in ("study", "solve"):
            self._send_error(400, "mode must be 'study' or 'solve'")
            return

        topics = [t.strip() for t in topics_str.split(",")] if topics_str else None

        try:
            with open(NEETCODE_PROBLEMS_FILE) as f:
                problems_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            problems_data = {"problems": []}

        if not problems_data.get("problems"):
            self._send_error(404, "No problems found")
            return

        full_profile = profile_io.load_profile()
        mode = profile_io.resolve_mode(full_profile, mode_arg)
        mode_state = profile_io.get_mode_state(full_profile, mode)
        # Project mode's ratings/review_history into the legacy shape nc-draw expects
        profile = {
            "ratings": mode_state["ratings"],
            "review_history": mode_state["review_history"],
        }

        if topics:
            for t in topics:
                if t not in NEETCODE_TOPIC_LABELS:
                    self._send_error(400, f"Unknown topic: {t}")
                    return

        problem = nc_draw.pick_problem(topics, difficulty, profile, problems_data)
        if not problem:
            self._send_error(404, "No problems available")
            return

        self._send_json({
            "id": problem["id"],
            "topic": problem.get("topic", "arrays-hashing"),
            "difficulty": problem.get("difficulty", "medium"),
            "blind": blind,
        })

    def _api_neetcode_rate(self):
        """POST /api/neetcode/rate — rate a problem with spaced repetition (mode-aware)."""
        from importlib import import_module
        import profile_io
        sr = import_module("spaced-repetition")

        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        problem_id = data.get("problem_id", "").strip()
        confidence = data.get("confidence")
        notes = data.get("notes")
        notes_only = data.get("notes_only", False)
        mode_arg = data.get("mode")

        if not problem_id:
            self._send_error(400, "problem_id is required")
            return
        if mode_arg is not None and mode_arg not in ("study", "solve"):
            self._send_error(400, "mode must be 'study' or 'solve'")
            return

        profile = profile_io.load_profile()
        try:
            mode = profile_io.resolve_mode(profile, mode_arg)
        except ValueError as e:
            self._send_error(400, str(e))
            return
        mode_state = profile_io.get_mode_state(profile, mode)
        ratings = mode_state["ratings"]

        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()

        # Notes-only update
        if notes_only:
            if not notes:
                self._send_error(400, "notes is required with notes_only")
                return
            existing = ratings.get(problem_id)
            if not existing:
                self._send_error(400, f"problem '{problem_id}' has not been rated in {mode} yet")
                return
            prev = existing.get("notes")
            if isinstance(prev, str):
                existing["notes"] = [{"text": prev, "ts": now}]
            elif not isinstance(prev, list):
                existing["notes"] = []
            existing["notes"].append({"text": notes, "ts": now})
            profile_io.save_profile(profile)
            self._send_json({"ok": True, "problem_id": problem_id, "mode": mode, "notes": existing["notes"]})
            return

        if not isinstance(confidence, int) or confidence < 1 or confidence > 5:
            self._send_error(400, "confidence must be 1-5")
            return

        existing = ratings.get(problem_id, {})
        is_new = problem_id not in ratings

        sr_fields = sr.compute_next_review(confidence, existing if existing else None)

        prev_notes = existing.get("notes")
        ratings[problem_id] = {
            "confidence": confidence,
            "last_rated": now,
            "times_seen": existing.get("times_seen", 0) + 1,
            **sr_fields,
        }
        if notes is not None:
            if isinstance(prev_notes, str):
                ratings[problem_id]["notes"] = [{"text": prev_notes, "ts": now}]
            elif isinstance(prev_notes, list):
                ratings[problem_id]["notes"] = list(prev_notes)
            else:
                ratings[problem_id]["notes"] = []
            ratings[problem_id]["notes"].append({"text": notes, "ts": now})
        elif prev_notes is not None:
            if isinstance(prev_notes, str):
                ratings[problem_id]["notes"] = [{"text": prev_notes, "ts": now}]
            else:
                ratings[problem_id]["notes"] = prev_notes

        mode_state["review_history"].append({
            "problem_id": problem_id,
            "rated_at": now,
            "confidence": confidence,
        })

        study_stats = profile.setdefault("study_stats", {"daily_goal": 3, "study_log": {}})
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_log = study_stats.setdefault("study_log", {}).setdefault(today_str, {"reviewed": 0, "new": 0})
        today_log["reviewed"] = today_log.get("reviewed", 0) + 1
        if is_new:
            today_log["new"] = today_log.get("new", 0) + 1

        profile_io.save_profile(profile)

        self._send_json({"ok": True, "problem_id": problem_id, "mode": mode,
                         "confidence": confidence,
                         "next_review": sr_fields["next_review"],
                         "mastery": sr.compute_mastery(ratings[problem_id])})

    # --- API Handlers: Guided Track ---

    def _api_neetcode_guided(self):
        """GET /api/neetcode/guided?mode=study|solve&both=1 — compute guided track state."""
        query = self._parse_query()
        both = query.get("both", "").lower() in ("1", "true", "yes")
        mode = query.get("mode") or None
        if mode and mode not in ("study", "solve"):
            self._send_error(400, "mode must be 'study' or 'solve'")
            return
        if both:
            import profile_io
            study = _compute_guided_track("study")
            solve = _compute_guided_track("solve")
            profile = profile_io.load_profile()
            self._send_json({
                "study": study,
                "solve": solve,
                "current_mode": profile.get("current_mode", "solve"),
            })
            return
        self._send_json(_compute_guided_track(mode))

    def _api_neetcode_guided_ordering(self):
        """GET /api/neetcode/guided/ordering — return deterministic list + cursors."""
        import profile_io
        try:
            with open(NEETCODE_PROBLEMS_FILE) as f:
                problems = json.load(f).get("problems", [])
        except (FileNotFoundError, json.JSONDecodeError):
            problems = []
        ordering = _build_guided_ordering(problems)
        profile = profile_io.load_profile()
        cursors = _compute_guided_cursors(problems, profile)
        self._send_json({
            "ordering": ordering,
            "cursors": cursors,
            "current_mode": profile.get("current_mode", "solve"),
        })

    def _api_neetcode_set_mode(self):
        """POST /api/neetcode/mode — set the default mode (study | solve)."""
        import profile_io
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        mode = (data.get("mode") or "").strip()
        if mode not in ("study", "solve"):
            self._send_error(400, "mode must be 'study' or 'solve'")
            return
        profile = profile_io.load_profile()
        profile["current_mode"] = mode
        profile_io.save_profile(profile)
        self._send_json({"ok": True, "current_mode": mode})

    # --- API Handlers: Stack ---

    def _api_stack_list(self):
        stack_data = _load_stack()
        self._send_json(stack_data)

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
        stack_data = _load_stack()
        first_lane = stack_data["lanes"][0]["id"] if stack_data["lanes"] else "lane-1"
        item = {
            "id": "stk-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
            "title": title,
            "source": data.get("source", "custom"),
            "boardSlug": data.get("boardSlug") or None,
            "notes": list(data.get("notes", [])),
            "lane": data.get("lane", first_lane),
            "createdAt": datetime.utcnow().isoformat() + "Z",
        }
        stack_data["items"].insert(0, item)
        _save_stack(stack_data)
        self._send_json({"item": item}, 201)

    def _api_stack_replace(self):
        """PUT /api/stack — replace entire stack (for reorder / bulk sync from frontend)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        # Accept new format { lanes, items } or legacy { items }
        items = data.get("items")
        if not isinstance(items, list):
            self._send_error(400, "items array is required")
            return
        lanes = data.get("lanes")
        stashed = data.get("stashedLanes")
        save_data = {"items": items}
        if isinstance(lanes, list):
            save_data["lanes"] = lanes
        else:
            save_data["lanes"] = _load_stack().get("lanes", [{"id": "lane-1", "label": "Lane 1"}])
        if isinstance(stashed, list) and stashed:
            save_data["stashedLanes"] = stashed
        _save_stack(save_data)
        self._send_json({"ok": True})

    def _api_stack_update(self, item_id):
        """PUT /api/stack/{id} — update a single stack item."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "Invalid JSON")
            return
        stack_data = _load_stack()
        target = None
        for it in stack_data["items"]:
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
        if "lane" in data:
            target["lane"] = data["lane"]
        _save_stack(stack_data)
        self._send_json({"item": target})

    def _api_stack_delete(self, item_id):
        """DELETE /api/stack/{id} — remove a stack item."""
        stack_data = _load_stack()
        new_items = [it for it in stack_data["items"] if it.get("id") != item_id]
        if len(new_items) == len(stack_data["items"]):
            self._send_error(404, "Stack item not found")
            return
        removed = [it for it in stack_data["items"] if it.get("id") == item_id][0]
        stack_data["items"] = new_items
        _save_stack(stack_data)
        self._send_json({"item": removed})


def main():
    import argparse
    import faulthandler
    faulthandler.enable()  # dump tracebacks on SIGSEGV/SIGABRT/hung threads

    parser = argparse.ArgumentParser(description="Mission Control Server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    server = ThreadingHTTPServer((HOST, args.port), DashboardHandler)
    server.daemon_threads = True
    server.timeout = 30  # accept() timeout — prevents blocking in select loop
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
