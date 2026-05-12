import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")

# Cadence step definitions
CADENCE_STEPS = [
    {"step": 1, "label": "Intro Message",   "type": "message",    "hours_after_prev": 0},
    {"step": 2, "label": "Voice Note 1",    "type": "voice_note", "hours_after_prev": 24},
    {"step": 3, "label": "Message 2",       "type": "message",    "hours_after_prev": 36},
    {"step": 4, "label": "Voice Note 2",    "type": "voice_note", "hours_after_prev": 12},
    {"step": 5, "label": "Message 3",       "type": "message",    "hours_after_prev": 12},
    {"step": 6, "label": "Message 4",       "type": "message",    "hours_after_prev": 12},
    {"step": 7, "label": "Voice Note 3",    "type": "voice_note", "hours_after_prev": 12},
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company TEXT,
                email TEXT,
                phone TEXT,
                linkedin_url TEXT,
                linkedin_profile_id TEXT UNIQUE,
                connected_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                current_step INTEGER NOT NULL DEFAULT 0,
                step_updated_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS step_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                step INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT (datetime('now')),
                notes TEXT,
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
            );
        """)


def row_to_dict(row):
    return dict(row) if row else None


def get_all_leads(status_filter=None):
    with get_db() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM leads WHERE status = ? ORDER BY step_updated_at ASC, connected_at ASC",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY step_updated_at ASC, connected_at ASC"
            ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_lead(lead_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return row_to_dict(row)


def create_lead(data):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO leads (name, company, email, phone, linkedin_url,
               linkedin_profile_id, connected_at, status, current_step, step_updated_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)""",
            (
                data.get("name"),
                data.get("company"),
                data.get("email"),
                data.get("phone"),
                data.get("linkedin_url"),
                data.get("linkedin_profile_id"),
                data.get("connected_at", datetime.utcnow().isoformat()),
                datetime.utcnow().isoformat(),
                data.get("notes"),
            ),
        )
        return cur.lastrowid


def update_lead(lead_id, data):
    allowed = {"name", "company", "email", "phone", "linkedin_url", "notes", "status", "connected_at"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        conn.execute(
            f"UPDATE leads SET {set_clause} WHERE id = ?",
            list(fields.values()) + [lead_id],
        )


def advance_step(lead_id, notes=None):
    lead = get_lead(lead_id)
    if not lead:
        return None
    new_step = lead["current_step"] + 1
    if new_step > len(CADENCE_STEPS):
        new_step = lead["current_step"]
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE leads SET current_step = ?, step_updated_at = ? WHERE id = ?",
            (new_step, now, lead_id),
        )
        if new_step > 0:
            step_info = CADENCE_STEPS[new_step - 1]
            conn.execute(
                "INSERT INTO step_history (lead_id, step, action_type, completed_at, notes) VALUES (?, ?, ?, ?, ?)",
                (lead_id, new_step, step_info["type"], now, notes),
            )
    return new_step


def get_step_history(lead_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM step_history WHERE lead_id = ? ORDER BY completed_at ASC",
            (lead_id,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_lead(lead_id):
    with get_db() as conn:
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))


def get_action_queue():
    """Return leads with their next due action, sorted by urgency."""
    from dateutil import parser as dateparser
    leads = get_all_leads(status_filter="active")
    queue = []
    now = datetime.utcnow()

    for lead in leads:
        step = lead["current_step"]
        if step >= len(CADENCE_STEPS):
            continue

        next_step_info = CADENCE_STEPS[step]

        if step == 0:
            # Next action: step 1 — due within 24h of connection
            ref_time_str = lead.get("connected_at") or lead["created_at"]
        else:
            ref_time_str = lead.get("step_updated_at") or lead["created_at"]

        try:
            ref_time = dateparser.parse(ref_time_str)
            if ref_time.tzinfo is not None:
                from datetime import timezone
                ref_time = ref_time.replace(tzinfo=None)
        except Exception:
            ref_time = now

        hours_offset = next_step_info["hours_after_prev"] if step > 0 else 0
        due_at = ref_time
        if step == 0:
            # Step 1 due within 24h of connection — show as due now if not started
            due_at = ref_time
        else:
            from datetime import timedelta
            due_at = ref_time + timedelta(hours=hours_offset)

        hours_until_due = (due_at - now).total_seconds() / 3600
        is_overdue = hours_until_due < 0

        queue.append({
            **lead,
            "next_step": step + 1,
            "next_action_label": next_step_info["label"],
            "next_action_type": next_step_info["type"],
            "due_at": due_at.isoformat(),
            "hours_until_due": round(hours_until_due, 1),
            "is_overdue": is_overdue,
        })

    queue.sort(key=lambda x: x["hours_until_due"])
    return queue
