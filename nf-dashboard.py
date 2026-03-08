#!/usr/bin/env python3
"""NoteFlow Interactive Web Dashboard — HTTP server + REST API."""

import json
import os
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    add_comment as mc_add_comment,
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
        elif parts == ["api", "archive"]:
            self._api_list_archive()
        elif parts == ["api", "board"]:
            self._api_board_get()
        elif parts == ["api", "board", "activity"]:
            self._api_board_list_activity()
        elif parts == ["api", "files"]:
            self._api_read_file()
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
        else:
            self._send_error(404, "Not found")

    def do_PUT(self):
        parts = self._parse_path()

        if len(parts) == 3 and parts[:2] == ["api", "items"]:
            self._api_update_item(parts[2])
        elif parts == ["api", "columns", "reorder"]:
            self._api_reorder_columns()
        elif parts == ["api", "board", "statuses", "reorder"]:
            self._api_board_reorder_statuses()
        elif parts == ["api", "board", "projects", "reorder"]:
            self._api_board_reorder_projects()
        elif len(parts) == 4 and parts[:3] == ["api", "board", "cards"]:
            self._api_board_update_card(parts[3])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "projects"]:
            self._api_board_update_project(parts[3])
        elif len(parts) == 6 and parts[:3] == ["api", "board", "projects"] and parts[4] == "phases":
            self._api_board_update_phase(parts[3], parts[5])
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
        elif len(parts) == 4 and parts[:3] == ["api", "board", "cards"]:
            self._api_board_delete_card(parts[3])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "statuses"]:
            self._api_board_delete_status(parts[3])
        elif len(parts) == 4 and parts[:3] == ["api", "board", "activity"]:
            self._api_board_delete_activity(parts[3])
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
            "linked_card": data.get("linked_card") or None,
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

    # --- API Handlers: File browsing ---

    _WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
    _ALLOWED_ROOTS = [
        os.path.expanduser("~/.openclaw/workspace"),
        os.path.expanduser("~/skill-backends"),
    ]

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
