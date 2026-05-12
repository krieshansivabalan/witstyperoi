import csv
import io
import json
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for

import database as db

app = Flask(__name__)
db.init_db()


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    queue = db.get_action_queue()
    stats = _stats()
    return render_template("dashboard.html", queue=queue, stats=stats, cadence=db.CADENCE_STEPS)


@app.route("/leads")
def leads_page():
    status = request.args.get("status", "")
    leads = db.get_all_leads(status_filter=status if status else None)
    return render_template("leads.html", leads=leads, status_filter=status, cadence=db.CADENCE_STEPS)


@app.route("/leads/<int:lead_id>")
def lead_detail(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return redirect(url_for("leads_page"))
    history = db.get_step_history(lead_id)
    return render_template("lead_detail.html", lead=lead, history=history, cadence=db.CADENCE_STEPS)


@app.route("/import")
def import_page():
    return render_template("import.html")


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/leads", methods=["GET"])
def api_get_leads():
    status = request.args.get("status")
    return jsonify(db.get_all_leads(status_filter=status))


@app.route("/api/leads", methods=["POST"])
def api_create_lead():
    data = request.get_json(force=True)
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    lead_id = db.create_lead(data)
    return jsonify({"id": lead_id}), 201


@app.route("/api/leads/<int:lead_id>", methods=["GET"])
def api_get_lead(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"error": "not found"}), 404
    return jsonify(lead)


@app.route("/api/leads/<int:lead_id>", methods=["PATCH"])
def api_update_lead(lead_id):
    data = request.get_json(force=True)
    db.update_lead(lead_id, data)
    return jsonify(db.get_lead(lead_id))


@app.route("/api/leads/<int:lead_id>", methods=["DELETE"])
def api_delete_lead(lead_id):
    db.delete_lead(lead_id)
    return jsonify({"ok": True})


@app.route("/api/leads/<int:lead_id>/advance", methods=["POST"])
def api_advance_step(lead_id):
    data = request.get_json(force=True) or {}
    new_step = db.advance_step(lead_id, notes=data.get("notes"))
    return jsonify({"step": new_step})


@app.route("/api/leads/<int:lead_id>/history", methods=["GET"])
def api_step_history(lead_id):
    return jsonify(db.get_step_history(lead_id))


@app.route("/api/queue", methods=["GET"])
def api_queue():
    return jsonify(db.get_action_queue())


@app.route("/api/import/csv", methods=["POST"])
def api_import_csv():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file"}), 400

    content = file.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))

    imported = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader):
        # Flexible column mapping — handle LinkedIn exports and custom CSVs
        name = (
            row.get("First Name", "") + " " + row.get("Last Name", "")
        ).strip() or row.get("name", "").strip() or row.get("Name", "").strip()

        if not name:
            skipped += 1
            continue

        data = {
            "name": name,
            "company": row.get("Company", row.get("company", row.get("Position", ""))),
            "email": row.get("Email Address", row.get("email", row.get("Email", ""))),
            "phone": row.get("phone", row.get("Phone", "")),
            "linkedin_url": row.get("URL", row.get("linkedin_url", row.get("Profile URL", ""))),
            "linkedin_profile_id": row.get("linkedin_profile_id", row.get("URL", "")),
            "connected_at": _parse_date(row.get("Connected On", row.get("connected_at", ""))),
            "notes": row.get("notes", ""),
        }

        try:
            db.create_lead(data)
            imported += 1
        except Exception as e:
            # Likely duplicate — skip
            skipped += 1

    return jsonify({"imported": imported, "skipped": skipped})


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _stats():
    all_leads = db.get_all_leads()
    total = len(all_leads)
    active = sum(1 for l in all_leads if l["status"] == "active")
    completed = sum(1 for l in all_leads if l["status"] == "completed")
    paused = sum(1 for l in all_leads if l["status"] == "paused")
    queue = db.get_action_queue()
    overdue = sum(1 for l in queue if l["is_overdue"])
    due_today = sum(1 for l in queue if not l["is_overdue"] and l["hours_until_due"] <= 24)
    return {
        "total": total,
        "active": active,
        "completed": completed,
        "paused": paused,
        "overdue": overdue,
        "due_today": due_today,
    }


def _parse_date(val):
    if not val:
        return datetime.utcnow().isoformat()
    from dateutil import parser as dp
    try:
        return dp.parse(val).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
