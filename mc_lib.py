"""Mission Control board library — load/save/CRUD for board.json."""

import json
import os
import re
import uuid
from datetime import datetime, timezone, timedelta

WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
BOARD_DIR = os.path.join(WORKSPACE, "mission-control")
BOARD_PATH = os.path.join(BOARD_DIR, "board.json")

# Built-in statuses that cannot be deleted
BUILTIN_STATUSES = {"pending", "active", "done"}

DEFAULT_STATUSES = [
    {"id": "pending", "label": "Pending", "color": "#f59e0b"},
    {"id": "active", "label": "Active", "color": "#3b82f6"},
    {"id": "done", "label": "Done", "color": "#10b981"},
]


def _now_iso():
    """Current local time in ISO 8601 with timezone offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _migrate_statuses(board):
    """Migrate plain-string statuses to object format if needed."""
    statuses = board.get("statuses", [])
    if not statuses:
        board["statuses"] = list(DEFAULT_STATUSES)
        return
    if isinstance(statuses[0], str):
        color_map = {"pending": "#f59e0b", "active": "#3b82f6", "done": "#10b981"}
        board["statuses"] = [
            {"id": s, "label": s.capitalize(), "color": color_map.get(s, "#64748b")}
            for s in statuses
        ]


def load_board():
    """Load board.json from disk. Returns default if missing. Auto-migrates statuses."""
    if not os.path.exists(BOARD_PATH):
        return {
            "projects": [],
            "statuses": list(DEFAULT_STATUSES),
            "cards": [],
            "decisions": [],
            "log": [],
            "activity": [],
            "next_id": 1,
        }
    with open(BOARD_PATH, "r") as f:
        board = json.load(f)
    _migrate_statuses(board)
    board.setdefault("activity", [])
    return board


def save_board(board):
    """Write board.json to disk (pretty-printed, atomic)."""
    os.makedirs(BOARD_DIR, exist_ok=True)
    tmp = BOARD_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(board, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, BOARD_PATH)


# ── Card helpers ──

def _make_slug(title):
    """Generate a URL-safe slug from a title."""
    import re
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def find_card(board, slug):
    """Find a card by slug. Returns the card dict or None."""
    for card in board["cards"]:
        if card["slug"] == slug:
            return card
    return None


def add_card(board, title, description="", status="pending", project=None, plan_file=None):
    """Add a new card. Returns the card."""
    now = _now_iso()
    card_id = f"mc-{board['next_id']:03d}"
    slug = _make_slug(title)

    # Ensure slug uniqueness
    existing_slugs = {c["slug"] for c in board["cards"]}
    base_slug = slug
    counter = 2
    while slug in existing_slugs:
        slug = f"{base_slug}-{counter}"
        counter += 1

    card = {
        "id": card_id,
        "slug": slug,
        "title": title,
        "description": description,
        "status": status,
        "project": project,
        "plan_file": plan_file,
        "created": now,
        "updated": now,
        "comments": [],
    }

    board["cards"].append(card)
    board["next_id"] += 1
    save_board(board)
    return card


def update_card(board, slug, updates):
    """Update fields on a card. Returns (card, error_msg)."""
    card = find_card(board, slug)
    if not card:
        return None, f"Card '{slug}' not found"

    allowed = {"title", "description", "status", "project", "plan_file"}
    for key, val in updates.items():
        if key in allowed:
            card[key] = val

    card["updated"] = _now_iso()
    save_board(board)
    return card, None


def delete_card(board, slug):
    """Delete a card. Returns (card, error_msg)."""
    card = find_card(board, slug)
    if not card:
        return None, f"Card '{slug}' not found"

    board["cards"] = [c for c in board["cards"] if c["slug"] != slug]
    save_board(board)
    return card, None


def _valid_status_ids(board):
    """Return set of valid status IDs from (possibly migrated) statuses."""
    return {s["id"] if isinstance(s, dict) else s for s in board.get("statuses", [])}


def move_card(board, slug, new_status):
    """Change a card's status. Returns (card, error_msg)."""
    card = find_card(board, slug)
    if not card:
        return None, f"Card '{slug}' not found"

    if new_status not in _valid_status_ids(board):
        return None, f"Invalid status '{new_status}'"

    card["status"] = new_status
    card["updated"] = _now_iso()
    save_board(board)
    return card, None


def add_comment(board, slug, text, author="cc"):
    """Add a comment to a card. Returns (card, error_msg)."""
    card = find_card(board, slug)
    if not card:
        return None, f"Card '{slug}' not found"

    card["comments"].append({
        "ts": _now_iso(),
        "author": author,
        "text": text,
    })
    card["updated"] = _now_iso()
    save_board(board)
    return card, None


# ── Project helpers ──

def find_project(board, project_id):
    """Find a project by ID. Returns the project dict or None."""
    for proj in board["projects"]:
        if proj["id"] == project_id:
            return proj
    return None


def add_project(board, project_id, name, spec=None, code=None, color="#6366f1"):
    """Add a project. Returns (project, error_msg)."""
    if find_project(board, project_id):
        return None, f"Project '{project_id}' already exists"

    proj = {
        "id": project_id,
        "name": name,
        "spec": spec,
        "code": code,
        "color": color,
    }
    board["projects"].append(proj)
    save_board(board)
    return proj, None


def update_project(board, project_id, updates):
    """Update project metadata. Returns (project, error_msg)."""
    proj = find_project(board, project_id)
    if not proj:
        return None, f"Project '{project_id}' not found"

    allowed = {"name", "spec", "code", "color", "summary", "vision", "phases", "links"}
    for key, val in updates.items():
        if key in allowed:
            proj[key] = val

    save_board(board)
    return proj, None


def update_phase(board, project_id, phase_index, new_status):
    """Update a single phase's status. Returns (project, error_msg)."""
    proj = find_project(board, project_id)
    if not proj:
        return None, f"Project '{project_id}' not found"

    phases = proj.get("phases", [])
    if phase_index < 0 or phase_index >= len(phases):
        return None, f"Phase index {phase_index} out of range (0-{len(phases) - 1})"

    valid = {"pending", "active", "done"}
    if new_status not in valid:
        return None, f"Invalid phase status '{new_status}' (must be pending/active/done)"

    phases[phase_index]["status"] = new_status
    save_board(board)
    return proj, None


def reorder_projects(board, order):
    """Reorder projects by ID list. Returns error_msg or None."""
    existing_ids = {p["id"] for p in board["projects"]}
    if set(order) != existing_ids:
        return "Order must contain exactly all existing project IDs"

    id_map = {p["id"]: p for p in board["projects"]}
    board["projects"] = [id_map[pid] for pid in order]
    save_board(board)
    return None


# ── Decisions & log ──

def add_decision(board, decision, context="", date=None):
    """Add a decision entry. Returns the entry."""
    entry = {
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "decision": decision,
        "context": context,
    }
    board["decisions"].append(entry)
    save_board(board)
    return entry


def add_log_entry(board, text, ts=None):
    """Add a log entry. Returns the entry."""
    entry = {
        "ts": ts or _now_iso(),
        "text": text,
    }
    board["log"].append(entry)
    save_board(board)
    return entry


# ── Status management ──

def _make_status_id(label):
    """Generate a slug ID from a status label."""
    sid = label.lower().strip()
    sid = re.sub(r"[^a-z0-9\s-]", "", sid)
    sid = re.sub(r"[\s_]+", "-", sid)
    sid = re.sub(r"-+", "-", sid).strip("-")
    return sid


def add_status(board, label, color="#64748b", position=None):
    """Add a custom status. Returns (status_obj, error_msg)."""
    sid = _make_status_id(label)
    existing_ids = {s["id"] for s in board["statuses"]}
    if sid in existing_ids:
        return None, f"Status '{sid}' already exists"

    status_obj = {"id": sid, "label": label, "color": color}
    if position is not None and 0 <= position <= len(board["statuses"]):
        board["statuses"].insert(position, status_obj)
    else:
        board["statuses"].append(status_obj)

    save_board(board)
    return status_obj, None


def delete_status(board, status_id):
    """Delete a custom status. Moves cards in that status to 'pending'. Returns (status_obj, error_msg)."""
    if status_id in BUILTIN_STATUSES:
        return None, f"Cannot delete built-in status '{status_id}'"

    found = None
    for s in board["statuses"]:
        if s["id"] == status_id:
            found = s
            break
    if not found:
        return None, f"Status '{status_id}' not found"

    board["statuses"] = [s for s in board["statuses"] if s["id"] != status_id]
    for card in board["cards"]:
        if card["status"] == status_id:
            card["status"] = "pending"
            card["updated"] = _now_iso()

    save_board(board)
    return found, None


def reorder_statuses(board, order):
    """Reorder statuses by ID list. Returns error_msg or None."""
    existing_ids = {s["id"] for s in board["statuses"]}
    if set(order) != existing_ids:
        return "Order must contain exactly all existing status IDs"

    id_map = {s["id"]: s for s in board["statuses"]}
    board["statuses"] = [id_map[sid] for sid in order]
    save_board(board)
    return None


# ── Activity log ──

def _make_activity_id():
    return f"act-{uuid.uuid4().hex[:8]}"


def add_activity(board, session, text, label=None, color=None):
    """Add a live activity entry. Returns the entry."""
    entry = {
        "id": _make_activity_id(),
        "session": session,
        "label": label or session[:2].upper(),
        "color": color or "#3b82f6",
        "text": text,
        "status": "active",
        "ts": _now_iso(),
    }
    board.setdefault("activity", []).append(entry)
    save_board(board)
    return entry


def clear_stale_activity(board, max_age_minutes=120):
    """Remove activity entries older than max_age_minutes. Returns count removed."""
    now = datetime.now().astimezone()
    cutoff = now - timedelta(minutes=max_age_minutes)
    original = board.get("activity", [])
    kept = []
    removed = 0
    for entry in original:
        try:
            ts = datetime.fromisoformat(entry["ts"])
            if ts >= cutoff:
                kept.append(entry)
            else:
                removed += 1
        except (ValueError, KeyError):
            kept.append(entry)
    board["activity"] = kept
    if removed:
        save_board(board)
    return removed


def list_activity(board, auto_clear=True):
    """Return activity list, optionally auto-clearing stale entries."""
    if auto_clear:
        clear_stale_activity(board)
    return board.get("activity", [])


def remove_activity(board, activity_id):
    """Remove a specific activity entry. Returns (entry, error_msg)."""
    activity = board.get("activity", [])
    found = None
    for entry in activity:
        if entry["id"] == activity_id:
            found = entry
            break
    if not found:
        return None, f"Activity '{activity_id}' not found"

    board["activity"] = [e for e in activity if e["id"] != activity_id]
    save_board(board)
    return found, None


def clear_all_activity(board):
    """Remove all activity entries."""
    board["activity"] = []
    save_board(board)
