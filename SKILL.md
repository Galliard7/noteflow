---
name: noteflow
description: "Frictionless capture system for tasks, ideas, notes, and reminders from natural conversation. Evaluate user messages for capture-worthy content: things they need to do, want to remember, ideas they express, deadlines, or reminder requests. Also use when user asks to see their tasks, notes, dashboard, what's on their plate, wants to mark items done or complete, undo a capture, or adjust a captured item. NOT for: questions directed at the agent, conversational replies, greetings, or meta-discussion about NoteFlow."
---

# NoteFlow

Frictionless thought capture and task management. Items are captured from natural conversation, classified, stored, and displayed without requiring commands.

## Core Behavior

**Always-on capture**: Evaluate every user message for capture-worthy content. When detected, immediately run the add script, then show the confirmation. The user does NOT need to ask for capture — detect it naturally.

**Write immediately, correct after**: Capture first, notify second. The user can say "undo" or adjust. Never ask for permission before capturing.

## What to Capture

Capture when the user expresses:

- Something they need to do → **task** ("I need to call the dentist", "should pick up groceries")
- An idea or possibility → **idea** ("maybe I should write a blog post about...", "what if we tried...")
- Something worth remembering → **note** ("Jake mentioned the deadline is March 15", "the API key format is...")
- A time-triggered reminder → **reminder** ("remind me tomorrow at 2pm to...", "don't forget to submit taxes by March 15")

## What NOT to Capture

- Questions directed at you ("how does X work?", "can you help me with...")
- Conversational replies ("yeah that makes sense", "ok", "thanks")
- Greetings and small talk ("hey", "good morning")
- NoteFlow meta-requests ("show me my tasks", "what's on my plate", "dashboard")
- Responses to your own questions
- Commands or instructions to you ("read this file", "search for...")

When uncertain whether something is capture-worthy, lean toward capturing and notifying — the user can always undo.

## Classification

| Type | Use when | Signals |
|---|---|---|
| **task** | Actionable item with a clear outcome | "need to", "should", "have to", "must", action verbs |
| **idea** | Potential action, not yet committed | "maybe", "what if", "could", "might be cool to" |
| **note** | Reference information worth remembering | Facts, names, dates, decisions, observations |
| **reminder** | Primary intent is "notify me at time X" | "remind me", "don't forget", explicit time with action |

If a message has both a task AND a time reference, classify as **task** with a `due` date. Use **reminder** only when the primary intent is time-triggered notification.

## Title Generation

Generate a clean, concise title (3-8 words) that captures core intent:

- "I really need to remember to call the dentist before this Friday" → **Call the dentist**
- "maybe we should try building a dashboard with React" → **Build a dashboard with React**
- "Jake said the deployment is scheduled for March 20" → **Deployment scheduled March 20**

## Timezone

User timezone: **America/Chicago**. Resolve all relative times ("tomorrow", "next Friday", "in 2 hours") to this timezone. Format as ISO 8601 with offset: `2026-03-06T09:00:00-06:00` (CST) or `-05:00` (CDT).

## Scripts

Base path: `~/skill-backends/noteflow`

### Add an item

```bash
python3 ~/skill-backends/noteflow/nf-add.py \
  --type <task|idea|note|reminder> \
  --title "<clean title>" \
  --body "<original user input verbatim>" \
  --due "<ISO 8601 datetime or omit>" \
  --remind "<ISO 8601 datetime or omit>" \
  --recurrence "<daily|weekdays|weekly|monthly or omit>"
```

Omit `--due` and `--remind` if not applicable.

When `--remind` is provided, a system cron job is automatically installed to deliver the reminder via Telegram at the exact time. When `--recurrence` is also set, the cron job repeats on that schedule.

| Recurrence | Meaning |
|---|---|
| `daily` | Every day at the remind time |
| `weekdays` | Monday–Friday at the remind time |
| `weekly` | Same weekday as the remind date, at that time |
| `monthly` | Same day-of-month as the remind date, at that time |
| *(omitted)* | One-shot: fires once, then self-cancels |

### View a specific item

```bash
python3 ~/skill-backends/noteflow/nf-view.py --id <nf-XXX>
```

Shows full details: title, type, status, due/remind dates, body, all subnotes, and recent history. Use when the user asks about a specific entry ("what's nf-002?", "show me that memory task", "details on nf-011").

### Add or delete a subnote

```bash
# Add a subnote
python3 ~/skill-backends/noteflow/nf-subnote.py --id <nf-XXX> --add "<text>"

# Delete a subnote by index
python3 ~/skill-backends/noteflow/nf-subnote.py --id <nf-XXX> --delete <index>
```

Use when the user wants to add a comment, update, or note to an existing entry ("add a note to nf-002", "comment on that task", "update nf-011 with..."). Subnote indices are shown by the view script.

### Update an entry's fields

```bash
python3 ~/skill-backends/noteflow/nf-update.py --id <nf-XXX> \
  --title "<new title>" \
  --body "<new body>" \
  --type <task|idea|note|reminder> \
  --due "<ISO 8601 or 'clear'>" \
  --remind "<ISO 8601 or 'clear'>" \
  --recurrence "<daily|weekdays|weekly|monthly or 'clear'>" \
  --add-tags tag1 tag2 \
  --remove-tags tag3 \
  --add-refs "https://example.com" "/path/to/file" \
  --remove-refs "https://old-url.com"
```

Use when the user wants to change an entry's title, body, type, dates, tags, or references. Only include the flags that need changing — omitted flags are left unchanged. Use `'clear'` as the value for `--due`, `--remind`, or `--recurrence` to remove them.

**References** are URLs, file paths, or any external pointers the user wants to attach to an entry ("link this to...", "add reference...", "attach this URL to nf-005").

### List active items (dashboard)

```bash
python3 ~/skill-backends/noteflow/nf-list.py
```

### Mark item done

```bash
python3 ~/skill-backends/noteflow/nf-done.py --id <nf-XXX>
```

### Manage reminders

```bash
# Set/install a cron reminder for an existing item
python3 ~/skill-backends/noteflow/nf-remind.py \
  --set <nf-XXX> --recurrence <daily|weekdays|weekly|monthly>

# Cancel a cron reminder
python3 ~/skill-backends/noteflow/nf-remind.py --cancel <nf-XXX>

# List active cron reminders
python3 ~/skill-backends/noteflow/nf-remind.py --list
```

Use `--set` when the user wants to add or change a recurring reminder on an existing item. Use `--cancel` when they say "stop reminding me about X" or "turn off that reminder".

### Undo last capture

```bash
python3 ~/skill-backends/noteflow/nf-undo.py
```

## Notification Format

After capture:

```
Captured → [nf-XXX] <title>
  Type: <type> | Due: <date if set> | Reminder: <date if set>
  (saved — say 'undo' or adjust)
```

After done: `Done ✓ [nf-XXX] <title>`

After undo: `Removed → [nf-XXX] <title>`

## Dashboard

When the user asks to see their items ("what's on my plate?", "show me my tasks", "dashboard"), run the list script and relay the output.

### Web Dashboard

A full interactive web dashboard is available:

```bash
python3 ~/skill-backends/noteflow/nf-dashboard.py
```

Opens `http://127.0.0.1:8765` in the default browser. The dashboard is **Mission Control** — a unified UI with two tabs:

- **NoteFlow tab:** Cards grouped by type (Reminders, Tasks, Ideas, Notes) with drag-and-drop, inline add, edit, mark done, sub-notes
- **Projects tab:** Kanban board for project/plan tracking. View by status (Pending/Active/Done) or by project. Card detail with comments, move, edit, delete.

Auto-refresh every 2 seconds. Options: `--port <N>`, `--no-open`.

### Mission Control CLI

Add progress comments to project cards:

```bash
python3 ~/skill-backends/noteflow/mc-comment.py \
  --plan "<card-slug>" --comment "<1-2 sentence update>"
```

Board data: `~/.openclaw/workspace/mission-control/board.json`
Plan files: `~/.openclaw/workspace/mission-control/plans/*.md`

## Status Changes

When the user wants to mark something done:

1. Run the list script to see current items
2. Identify which item they mean
3. **Always confirm before changing status** — show the matching item, ask "Mark as done?"
4. Only after explicit confirmation, run the done script

When multiple items could match, show all candidates and ask which one.

## Adjustments

When the user wants to adjust a recently captured item:

1. Run undo to remove the current version
2. Re-add with corrected fields
3. Show updated confirmation

## Context Recovery

After context compaction, run the list script to re-read current items before any NoteFlow operation.

## Data Location

**Canonical data path:** `~/.openclaw/workspace/data/noteflow/`

Store: `~/.openclaw/workspace/data/noteflow/store.json` — single source of truth across all channels (Telegram, Discord, browser gateway, etc.). NoteFlow is one unified board.

**Always use the scripts** to read and modify the store. Never write to `store.json` directly via file tools.
