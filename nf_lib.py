"""NoteFlow shared library — store operations and utilities."""

import json
import os
from datetime import datetime, timedelta

WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
STORE_DIR = os.path.join(WORKSPACE, "data", "noteflow")
STORE_PATH = os.path.join(STORE_DIR, "store.json")
ARCHIVE_PATH = os.path.join(STORE_DIR, "archive.json")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
def _resolve_telegram_chat_id():
    """Resolve Telegram chat ID from env var or cc-remote state."""
    env_val = os.environ.get("TELEGRAM_CHAT_ID")
    if env_val:
        return env_val
    # Fallback: read from cc-remote's persisted state
    cc_state_path = os.path.join(WORKSPACE, "data", "cc-remote", "state.json")
    if os.path.exists(cc_state_path):
        try:
            with open(cc_state_path) as f:
                state = json.load(f)
            cid = state.get("handoff", {}).get("chat_id")
            if cid:
                return str(cid)
        except (json.JSONDecodeError, IOError):
            pass
    return ""


TELEGRAM_CHAT_ID = _resolve_telegram_chat_id()


DEFAULT_COLUMNS = [
    {"id": "task", "label": "Tasks", "icon": "\u2611", "color": "#3b82f6"},
    {"id": "reminder", "label": "Reminders", "icon": "\U0001F514", "color": "#ef4444"},
    {"id": "idea", "label": "Ideas", "icon": "\U0001F4A1", "color": "#f59e0b"},
    {"id": "note", "label": "Notes", "icon": "\U0001F4DD", "color": "#10b981"},
]


def _migrate_linked_cards(store):
    """Migrate linked_card (string|null) → linked_cards (array). Idempotent."""
    changed = False
    for item in store.get("items", []):
        if "linked_card" in item:
            old = item.pop("linked_card")
            item["linked_cards"] = [old] if old else []
            changed = True
        elif "linked_cards" not in item:
            item["linked_cards"] = []
            changed = True
    return changed


def load_store():
    """Load the NoteFlow store from disk. Returns default if missing."""
    if not os.path.exists(STORE_PATH):
        return {"next_id": 1, "timezone": "America/Chicago", "items": [], "columns": list(DEFAULT_COLUMNS)}
    with open(STORE_PATH, "r") as f:
        store = json.load(f)
    # Ensure columns exist (backward compat)
    if "columns" not in store:
        store["columns"] = list(DEFAULT_COLUMNS)
    # Migrate linked_card → linked_cards
    if _migrate_linked_cards(store):
        save_store(store)
    return store


def save_store(store):
    """Write the NoteFlow store to disk (pretty-printed JSON)."""
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, STORE_PATH)


def now_iso():
    """Current local time in ISO 8601 with timezone offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def format_id(num):
    """Format a numeric ID as nf-XXX."""
    return f"nf-{num:03d}"


def find_item(store, item_id):
    """Find an item by ID. Returns the item dict or None."""
    for item in store["items"]:
        if item["id"] == item_id:
            return item
    return None


def update_item(store, item_id, updates):
    """Update fields on an item. Returns (item, error_msg).

    Allowed fields: title, body, tags, due, remind, recurrence.
    """
    item = find_item(store, item_id)
    if not item:
        return None, f"Item {item_id} not found"

    allowed = {"title", "body", "tags", "due", "remind", "recurrence", "type", "linked_cards", "references"}
    changes = []
    for key, val in updates.items():
        if key in allowed:
            item[key] = val
            changes.append(key)

    if changes:
        item.setdefault("history", []).append(
            {"ts": now_iso(), "action": f"updated: {', '.join(changes)}"}
        )
        save_store(store)

    return item, None


def add_subnote(store, item_id, text):
    """Add a timestamped sub-note to an item. Returns (item, error_msg)."""
    item = find_item(store, item_id)
    if not item:
        return None, f"Item {item_id} not found"

    item.setdefault("subnotes", []).append({"ts": now_iso(), "text": text})
    item.setdefault("history", []).append(
        {"ts": now_iso(), "action": "subnote added"}
    )
    save_store(store)
    return item, None


def delete_subnote(store, item_id, index):
    """Remove a sub-note by index. Returns (item, error_msg)."""
    item = find_item(store, item_id)
    if not item:
        return None, f"Item {item_id} not found"

    subnotes = item.get("subnotes", [])
    if index < 0 or index >= len(subnotes):
        return None, f"Sub-note index {index} out of range"

    subnotes.pop(index)
    item.setdefault("history", []).append(
        {"ts": now_iso(), "action": "subnote removed"}
    )
    save_store(store)
    return item, None


def delete_item(store, item_id):
    """Delete an item from the store. Returns (item, error_msg)."""
    item = find_item(store, item_id)
    if not item:
        return None, f"Item {item_id} not found"

    store["items"] = [i for i in store["items"] if i["id"] != item_id]
    save_store(store)
    return item, None


def reopen_item(store, item_id):
    """Reopen a done item. Returns (item, error_msg)."""
    item = find_item(store, item_id)
    if not item:
        return None, f"Item {item_id} not found"
    if item["status"] != "done":
        return None, f"Item {item_id} is not done (status: {item['status']})"

    item["status"] = "open"
    item.setdefault("history", []).append(
        {"ts": now_iso(), "action": "reopened"}
    )
    save_store(store)
    return item, None


def get_columns(store):
    """Return the list of columns (types)."""
    return store.get("columns", list(DEFAULT_COLUMNS))


def add_column(store, col_id, label, color="#6366f1", icon="\U0001F4CC"):
    """Add a custom column. Returns (column, error_msg)."""
    col_id = col_id.lower().replace(" ", "-")
    existing_ids = {c["id"] for c in store.get("columns", [])}
    if col_id in existing_ids:
        return None, f"Column '{col_id}' already exists"

    col = {"id": col_id, "label": label, "icon": icon, "color": color}
    store.setdefault("columns", list(DEFAULT_COLUMNS)).append(col)
    save_store(store)
    return col, None


def delete_column(store, col_id):
    """Delete a custom column. Built-in types cannot be deleted.
    Items with this type are moved to 'task'. Returns (col, error_msg)."""
    builtin = {"task", "reminder", "idea", "note"}
    if col_id in builtin:
        return None, f"Cannot delete built-in column '{col_id}'"

    columns = store.get("columns", [])
    col = None
    for c in columns:
        if c["id"] == col_id:
            col = c
            break
    if not col:
        return None, f"Column '{col_id}' not found"

    store["columns"] = [c for c in columns if c["id"] != col_id]
    # Move orphaned items to 'task'
    for item in store["items"]:
        if item["type"] == col_id:
            item["type"] = "task"
    save_store(store)
    return col, None


def reorder_columns(store, column_ids):
    """Reorder columns to match the given list of IDs. Returns error_msg or None."""
    columns = store.get("columns", [])
    col_map = {c["id"]: c for c in columns}
    reordered = []
    for cid in column_ids:
        if cid in col_map:
            reordered.append(col_map[cid])
    # Append any columns not in the list (safety)
    seen = set(column_ids)
    for c in columns:
        if c["id"] not in seen:
            reordered.append(c)
    store["columns"] = reordered
    save_store(store)
    return None


def load_archive():
    """Load the NoteFlow archive from disk. Returns list of archived items."""
    if not os.path.exists(ARCHIVE_PATH):
        return []
    with open(ARCHIVE_PATH, "r") as f:
        return json.load(f)


def save_archive(items):
    """Write the NoteFlow archive to disk."""
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = ARCHIVE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, ARCHIVE_PATH)


def archive_done_items(store):
    """Move done items older than 7 days to archive.json. Modifies store in place."""
    cutoff = datetime.now().astimezone() - timedelta(days=7)
    to_archive = []
    remaining = []

    for item in store["items"]:
        if item["status"] != "done":
            remaining.append(item)
            continue

        # Find the 'done' timestamp from history
        done_ts = None
        for h in reversed(item.get("history", [])):
            act = h["action"]
            if act == "done" or act == "completed" or act.startswith("done "):
                try:
                    done_ts = datetime.fromisoformat(h["ts"])
                except (ValueError, TypeError):
                    pass
                break

        if done_ts and done_ts < cutoff:
            item["archived_at"] = now_iso()
            to_archive.append(item)
        else:
            remaining.append(item)

    if to_archive:
        archive = load_archive()
        archive.extend(to_archive)
        save_archive(archive)
        store["items"] = remaining
        save_store(store)
