"""
app.py — Traffic E-Challan Web Portal (Enhanced)
=================================================
Routes:
  /                              → Login / Logout
  /admin/dashboard               → Stats + challan list + filters
  /admin/challan/<id>            → View / edit / delete challan
  /admin/challan/<id>/status     → AJAX status toggle
  /admin/vehicle/<plate>         → Full vehicle registration details + history
  /admin/registrations           → List all registrations
  /admin/registrations/add       → Add registration
  /admin/registrations/<id>/edit → Edit registration
  /admin/registrations/<id>/delete → Delete registration
  /admin/users                   → Manage user accounts
  /admin/users/add               → Add user
  /admin/users/<id>/delete       → Delete user
  /admin/export                  → Export challans CSV
  /admin/import-csv              → Import challans from CSV
  /admin/manual-challan          → Issue manual/virtual challan by plate number
  /admin/api/vehicle/<plate>     → JSON vehicle info (AJAX modal)
  /admin/notifications           → View all notifications
  /user/dashboard                → User: own challans + stats
  /user/challan/<id>             → User: single challan detail
  /user/notifications            → User: own notifications
  /logout                        → Clear session
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, send_file)
import sqlite3
import csv
import io
import os
import time
import random
from functools import wraps
from datetime import datetime, date

try:
    from sms_service import (send_challan_sms, send_challan_email,
                              send_payment_confirmation_sms,
                              SMTP_USER, FAST2SMS_API_KEY)
    EMAIL_ENABLED = ("your_gmail" not in SMTP_USER and "@" in SMTP_USER)
    SMS_ENABLED_FLAG = ("your_fast2sms" not in FAST2SMS_API_KEY and len(FAST2SMS_API_KEY) > 10)
    SMS_ENABLED = True   # module loaded; individual flags control actual sending
except ImportError:
    EMAIL_ENABLED = False
    SMS_ENABLED_FLAG = False
    SMS_ENABLED = False
    def send_challan_sms(*a, **kw): return False
    def send_challan_email(*a, **kw): return False
    def send_payment_confirmation_sms(*a, **kw): return False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "traffic_echallan_secret_2025")
import pathlib as _pl
DB_PATH = str(_pl.Path(__file__).parent.absolute() / "database.db")


# ─── DB ──────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def validity_status(date_str: str) -> str:
    """Return 'valid', 'expiring' (≤30 days), or 'expired'."""
    if not date_str:
        return "unknown"
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        diff = (d - date.today()).days
        if diff < 0:
            return "expired"
        if diff <= 30:
            return "expiring"
        return "valid"
    except Exception:
        return "unknown"


app.jinja_env.globals["validity_status"] = validity_status
app.jinja_env.globals["today"] = date.today

import json as _json_mod
app.jinja_env.filters["fromjson"] = _json_mod.loads

def _ts_to_dt(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)
app.jinja_env.filters["timestamp_to_dt"] = _ts_to_dt


# ─── Decorators ──────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if "username" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if session.get("role") != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapped


# ─── Context: unread notification count ──────────────────────────────────────

@app.context_processor
def inject_notifications():
    if "user_id" in session:
        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
            (session["user_id"],)
        ).fetchone()[0]
        conn.close()
        return {"unread_count": count}
    return {"unread_count": 0}


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(
            url_for("admin_dashboard") if session.get("role") == "admin"
            else url_for("user_dashboard")
        )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session.update({
                "username":  user["username"],
                "role":      user["role"],
                "vehicle":   user["vehicle"],
                "user_id":   user["id"],
                "full_name": user["full_name"] or user["username"],
            })
            return redirect(
                url_for("admin_dashboard") if user["role"] == "admin"
                else url_for("user_dashboard")
            )
        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Admin: Live Challan Count API ──────────────────────────────────────────

@app.route("/admin/api/challan-count")
@login_required
@admin_required
def api_challan_count():
    """Returns latest challan count + most recent challan — used for live refresh."""
    conn    = get_db()
    count   = conn.execute("SELECT COUNT(*) FROM challans").fetchone()[0]
    latest  = conn.execute(
        "SELECT id, challan_no, plate, speed, datetime, fine_amount, status FROM challans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return jsonify({
        "count":  count,
        "latest": dict(latest) if latest else None,
    })


# ─── Admin: Quick Action (AJAX) ──────────────────────────────────────────────



# ─── Admin: Auto-Detected Challans Feed (AJAX) ───────────────────────────────

@app.route("/admin/api/auto-challans")
@login_required
@admin_required
def api_auto_challans():
    """Returns the latest auto-detected challans for the live feed panel."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, challan_no, plate, speed, speed_limit, vehicle_type,
               datetime, area, fine_amount, status, image
        FROM challans
        ORDER BY id DESC LIMIT 10
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/admin/api/simulate-violation", methods=["POST"])
@login_required
@admin_required
def simulate_violation():
    """
    Demo endpoint: creates a realistic auto-detection challan from a registered
    vehicle so the dashboard live-feed works even without the camera running.
    """
    import random
    conn = get_db()

    # Cycle through the 3 real-email plates in order, then random
    TARGET_PLATES = ['RJ14AB1234', 'RJ14CD5678', 'RJ14EF9012']
    already_done = conn.execute(
        "SELECT COUNT(*) FROM challans WHERE plate IN ('RJ14AB1234','RJ14CD5678','RJ14EF9012')"
    ).fetchone()[0]
    target_plate = TARGET_PLATES[already_done % len(TARGET_PLATES)]
    plates = conn.execute(
        "SELECT plate, owner_name, email, phone FROM vehicle_registrations WHERE plate=?",
        (target_plate,)
    ).fetchone()
    if not plates:
        plates = conn.execute(
            "SELECT plate, owner_name, email, phone FROM vehicle_registrations ORDER BY RANDOM() LIMIT 1"
        ).fetchone()

    if not plates:
        conn.close()
        return jsonify({"success": False, "error": "No registered vehicles in DB"})

    plate       = plates["plate"]
    speed_limit = 40
    speed       = random.randint(speed_limit + 5, speed_limit + 60)
    excess      = speed - speed_limit
    fine        = 1000 if excess <= 20 else (2000 if excess <= 40 else 5000)
    areas       = ["Ajmer Road, Jaipur", "Tonk Road, Jaipur", "Sikar Road, Jaipur",
                   "MI Road, Jaipur", "JLN Marg, Jaipur"]
    area        = random.choice(areas)
    vtypes      = ["Car", "Bike", "Bus", "Truck"]
    vtype       = random.choice(vtypes)
    challan_no  = f"AUTO{int(time.time())}{random.randint(10,99)}"
    now_str     = time.strftime("%Y-%m-%d %H:%M:%S")

    c = conn.cursor()
    c.execute("""
        INSERT INTO challans
          (challan_no,timestamp,vehicle_type,plate,speed,speed_limit,
           datetime,area,image,status,fine_amount)
        VALUES (?,?,?,?,?,?,?,?,?,'Unpaid',?)
    """, (challan_no, int(time.time()), vtype, plate, speed, speed_limit,
          now_str, area, "", fine))
    challan_id = c.lastrowid

    # In-app notification
    user = conn.execute("SELECT id FROM users WHERE vehicle=?", (plate,)).fetchone()
    if user:
        msg = (f"\u26a0\ufe0f Auto Challan #{challan_no}: {plate} detected at {speed} km/h "
               f"in {area}. Fine: Rs.{fine:,}")
        c.execute("""INSERT INTO notifications (user_id,plate,challan_id,message)
                     VALUES (?,?,?,?)""", (user["id"], plate, challan_id, msg))

    conn.commit()

    # Send email/SMS automatically
    owner_name = plates["owner_name"]
    email_addr = plates["email"]
    phone      = plates["phone"]

    email_sent = False
    sms_sent   = False
    if email_addr and EMAIL_ENABLED:
        email_sent = bool(send_challan_email(email_addr, plate, speed, speed_limit,
                                              area, challan_no, fine))
    if phone and SMS_ENABLED_FLAG:
        sms_sent = bool(send_challan_sms(phone, plate, speed, speed_limit,
                                          area, challan_no, fine))
    conn.close()

    return jsonify({
        "success":    True,
        "challan_no": challan_no,
        "plate":      plate,
        "speed":      speed,
        "fine":       fine,
        "area":       area,
        "vtype":      vtype,
        "owner":      owner_name,
        "email_sent": email_sent,
        "sms_sent":   sms_sent,
        "datetime":   now_str,
    })

@app.route("/admin/quick-challan", methods=["POST"])
@login_required
@admin_required
def quick_challan():
    """Issue a challan instantly from the dashboard modal."""
    f       = request.get_json() or {}
    plate   = f.get("plate", "").strip().upper()
    speed   = int(f.get("speed", 0) or 0)
    limit   = int(f.get("speed_limit", 60) or 60)
    area    = f.get("area", "Ajmer Road, Jaipur").strip()
    vtype   = f.get("vehicle_type", "Car")

    if not plate:
        return jsonify({"success": False, "error": "Plate number required"})

    excess = speed - limit
    if excess <= 0:   fine = 1000
    elif excess <= 20: fine = 1000
    elif excess <= 40: fine = 2000
    else:              fine = 5000

    challan_no = f"MCH{int(time.time())}{random.randint(100,999)}"
    dt_str     = time.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO challans
          (challan_no,timestamp,vehicle_type,plate,speed,speed_limit,
           datetime,area,image,status,fine_amount)
        VALUES (?,?,?,?,?,?,?,?,?,'Unpaid',?)
    """, (challan_no, int(time.time()), vtype, plate, speed, limit,
          dt_str, area, "", fine))
    challan_id = c.lastrowid

    # in-app notification
    user = conn.execute("SELECT id FROM users WHERE vehicle=?", (plate,)).fetchone()
    if user:
        conn.execute("""INSERT INTO notifications (user_id,plate,challan_id,message)
            VALUES (?,?,?,?)""",
            (user["id"], plate, challan_id,
             f"⚠️ Challan #{challan_no}: {plate} at {speed}km/h in {area}. Fine: Rs.{fine:,}"))
    conn.commit()

    # send email + sms
    owner = conn.execute(
        "SELECT owner_name,phone,email FROM vehicle_registrations WHERE plate=?", (plate,)
    ).fetchone()
    if not owner:
        owner = conn.execute(
            "SELECT full_name as owner_name,phone,email FROM users WHERE vehicle=?", (plate,)
        ).fetchone()

    email_sent = sms_sent = False
    owner_name = phone = email = ""
    no_record  = True

    if owner:
        no_record  = False
        owner_name = owner["owner_name"] or ""
        phone      = owner["phone"] or ""
        email      = owner["email"] or ""
        if email:
            email_sent = bool(send_challan_email(email, plate, speed, limit, area, challan_no, fine))
        if phone:
            sms_sent   = bool(send_challan_sms(phone, plate, speed, limit, area, challan_no, fine))

    conn.close()
    return jsonify({
        "success":    True,
        "challan_no": challan_no,
        "fine":       fine,
        "owner_name": owner_name,
        "phone":      phone,
        "email":      email,
        "email_sent": email_sent,
        "sms_sent":   sms_sent,
        "no_record":  no_record,
    })


@app.route("/admin/quick-notify/<int:cid>", methods=["POST"])
@login_required
@admin_required
def quick_notify(cid):
    """Re-send notification for an existing challan from dashboard."""
    conn    = get_db()
    challan = conn.execute("SELECT * FROM challans WHERE id=?", (cid,)).fetchone()
    if not challan:
        conn.close()
        return jsonify({"success": False, "error": "Challan not found"})

    owner = conn.execute(
        "SELECT owner_name,phone,email FROM vehicle_registrations WHERE plate=?",
        (challan["plate"],)
    ).fetchone()
    if not owner:
        owner = conn.execute(
            "SELECT full_name as owner_name,phone,email FROM users WHERE vehicle=?",
            (challan["plate"],)
        ).fetchone()
    conn.close()

    if not owner:
        return jsonify({"success": False, "error": "No owner record found for this plate"})

    email_sent = sms_sent = False
    if owner["email"]:
        email_sent = bool(send_challan_email(
            owner["email"], challan["plate"], challan["speed"],
            challan["speed_limit"], challan["area"],
            challan["challan_no"], challan["fine_amount"]))
    if owner["phone"]:
        sms_sent = bool(send_challan_sms(
            owner["phone"], challan["plate"], challan["speed"],
            challan["speed_limit"], challan["area"],
            challan["challan_no"], challan["fine_amount"]))

    return jsonify({
        "success":    True,
        "email":      owner["email"] or "",
        "phone":      owner["phone"] or "",
        "email_sent": email_sent,
        "sms_sent":   sms_sent,
    })


# ─── Admin: Dashboard ────────────────────────────────────────────────────────

@app.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    conn = get_db()

    status_f = request.args.get("status", "")
    area_f   = request.args.get("area", "")
    plate_f  = request.args.get("plate", "")
    date_f   = request.args.get("date", "")

    q      = "SELECT * FROM challans WHERE 1=1"
    params = []
    if status_f:
        q += " AND status=?"; params.append(status_f)
    if area_f:
        q += " AND area LIKE ?"; params.append(f"%{area_f}%")
    if plate_f:
        q += " AND plate LIKE ?"; params.append(f"%{plate_f.upper()}%")
    if date_f:
        q += " AND datetime LIKE ?"; params.append(f"{date_f}%")
    q += " ORDER BY timestamp DESC"

    challans = conn.execute(q, params).fetchall()

    stats = conn.execute("""
        SELECT
            COUNT(*)                                             AS total,
            SUM(CASE WHEN status='Unpaid' THEN 1 ELSE 0 END)    AS unpaid,
            SUM(CASE WHEN status='Paid'   THEN 1 ELSE 0 END)    AS paid,
            SUM(CASE WHEN status='Paid'   THEN fine_amount ELSE 0 END) AS revenue,
            SUM(CASE WHEN vehicle_type='Car'   THEN 1 ELSE 0 END) AS cars,
            SUM(CASE WHEN vehicle_type='Bike'  THEN 1 ELSE 0 END) AS bikes,
            SUM(CASE WHEN vehicle_type='Bus'   THEN 1 ELSE 0 END) AS buses,
            SUM(CASE WHEN vehicle_type='Truck' THEN 1 ELSE 0 END) AS trucks,
            ROUND(AVG(speed),1)  AS avg_speed,
            MAX(speed)           AS max_speed,
            SUM(fine_amount)     AS total_fine
        FROM challans
    """).fetchone()

    areas = [r[0] for r in conn.execute(
        "SELECT DISTINCT area FROM challans ORDER BY area"
    ).fetchall()]

    # Recent 7-day daily count for mini chart
    daily = conn.execute("""
        SELECT date(datetime) as d, COUNT(*) as cnt
        FROM challans
        WHERE date(datetime) >= date('now','-6 days')
        GROUP BY d ORDER BY d
    """).fetchall()

    conn.close()
    return render_template(
        "admin_dashboard.html",
        challans=challans, stats=stats, areas=areas,
        daily_data=list(daily),
        status_filter=status_f, area_filter=area_f,
        plate_filter=plate_f, date_filter=date_f,
    )


# ─── Admin: Vehicle Details (full page) ──────────────────────────────────────

@app.route("/admin/vehicle/<plate>")
@login_required
@admin_required
def admin_vehicle_details(plate):
    plate = plate.upper()
    conn  = get_db()

    reg = conn.execute(
        "SELECT * FROM vehicle_registrations WHERE plate=?", (plate,)
    ).fetchone()

    challans = conn.execute(
        "SELECT * FROM challans WHERE plate=? ORDER BY timestamp DESC",
        (plate,)
    ).fetchall()

    ch_stats = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='Unpaid' THEN 1 ELSE 0 END) as unpaid,
               SUM(CASE WHEN status='Paid'   THEN 1 ELSE 0 END) as paid,
               SUM(fine_amount) as total_fine,
               MAX(speed) as max_speed
        FROM challans WHERE plate=?
    """, (plate,)).fetchone()

    user = conn.execute(
        "SELECT * FROM users WHERE vehicle=?", (plate,)
    ).fetchone()

    conn.close()
    return render_template(
        "admin_vehicle_details.html",
        reg=reg, plate=plate,
        challans=challans, ch_stats=ch_stats, user=user,
    )


# ─── Admin: Vehicle Info JSON (AJAX modal) ───────────────────────────────────

@app.route("/admin/api/vehicle/<plate>")
@login_required
@admin_required
def api_vehicle_info(plate):
    plate = plate.upper()
    conn  = get_db()

    reg = conn.execute(
        "SELECT * FROM vehicle_registrations WHERE plate=?", (plate,)
    ).fetchone()

    user = conn.execute(
        "SELECT full_name, email, phone FROM users WHERE vehicle=?", (plate,)
    ).fetchone()

    challan_count = conn.execute(
        "SELECT COUNT(*) FROM challans WHERE plate=?", (plate,)
    ).fetchone()[0]

    conn.close()

    if reg:
        def vs(d):
            return validity_status(d)
        data = dict(reg)
        data["validity_status_rc"]        = vs(data.get("validity_date",""))
        data["validity_status_insurance"] = vs(data.get("insurance_validity",""))
        data["validity_status_fitness"]   = vs(data.get("fitness_validity",""))
        data["validity_status_tax"]       = vs(data.get("tax_validity",""))
        data["challan_count"]             = challan_count
        return jsonify({"found": True, "data": data})

    # Fallback from users table
    if user:
        return jsonify({"found": True, "partial": True, "data": dict(user)})

    return jsonify({"found": False, "plate": plate})


# ─── Admin: Edit / Delete Challan ─────────────────────────────────────────────

@app.route("/admin/challan/<int:cid>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_challan(cid):
    conn    = get_db()
    challan = conn.execute(
        "SELECT * FROM challans WHERE id=?", (cid,)
    ).fetchone()

    if not challan:
        conn.close()
        flash("Challan not found.", "error")
        return redirect(url_for("admin_dashboard"))

    reg = conn.execute(
        "SELECT * FROM vehicle_registrations WHERE plate=?",
        (challan["plate"],)
    ).fetchone()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update":
            new_status = request.form.get("status")
            new_area   = request.form.get("area")
            paid_at    = None
            if new_status == "Paid":
                paid_at = time.strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE challans SET status=?, area=?, paid_at=? WHERE id=?",
                (new_status, new_area, paid_at, cid)
            )
            conn.commit()
            if new_status == "Paid" and SMS_ENABLED:
                owner = conn.execute(
                    "SELECT phone FROM users WHERE vehicle=?",
                    (challan["plate"],)
                ).fetchone()
                if owner:
                    send_payment_confirmation_sms(
                        owner["phone"], challan["plate"], cid
                    )
            flash(f"Challan #{challan['challan_no']} updated.", "success")

        elif action == "delete":
            conn.execute("DELETE FROM challans WHERE id=?", (cid,))
            conn.commit()
            conn.close()
            flash(f"Challan #{challan['challan_no']} deleted.", "success")
            return redirect(url_for("admin_dashboard"))

        conn.close()
        return redirect(url_for("admin_dashboard"))

    conn.close()
    return render_template("edit_challan.html", challan=challan, reg=reg)


@app.route("/admin/challan/<int:cid>/status", methods=["POST"])
@login_required
@admin_required
def update_challan_status(cid):
    data       = request.get_json() or {}
    new_status = data.get("status", "Unpaid")
    paid_at    = time.strftime("%Y-%m-%d %H:%M:%S") if new_status == "Paid" else None

    conn = get_db()
    conn.execute(
        "UPDATE challans SET status=?, paid_at=? WHERE id=?",
        (new_status, paid_at, cid)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "status": new_status})


# ─── Admin: Vehicle Registrations ────────────────────────────────────────────

@app.route("/admin/registrations")
@login_required
@admin_required
def admin_registrations():
    conn  = get_db()
    search = request.args.get("q", "").strip()
    if search:
        regs = conn.execute("""
            SELECT * FROM vehicle_registrations
            WHERE plate LIKE ? OR owner_name LIKE ? OR phone LIKE ?
            ORDER BY plate
        """, (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    else:
        regs = conn.execute(
            "SELECT * FROM vehicle_registrations ORDER BY plate"
        ).fetchall()
    conn.close()
    return render_template("admin_registrations.html", regs=regs, search=search)


@app.route("/admin/registrations/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_registration():
    if request.method == "POST":
        f   = request.form
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO vehicle_registrations
                  (plate,owner_name,email,phone,address,vehicle_make,vehicle_model,
                   vehicle_color,vehicle_year,rc_number,registration_date,validity_date,
                   insurance_validity,fitness_validity,tax_validity,dl_number)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f.get("plate","").upper(), f.get("owner_name",""),
                f.get("email",""), f.get("phone",""), f.get("address",""),
                f.get("vehicle_make",""), f.get("vehicle_model",""),
                f.get("vehicle_color",""), int(f.get("vehicle_year",0) or 0),
                f.get("rc_number",""), f.get("registration_date",""),
                f.get("validity_date",""), f.get("insurance_validity",""),
                f.get("fitness_validity",""), f.get("tax_validity",""),
                f.get("dl_number",""),
            ))
            conn.commit()
            flash(f"Registration for {f.get('plate','').upper()} added.", "success")
        except sqlite3.IntegrityError:
            flash("Plate already registered.", "error")
        finally:
            conn.close()
        return redirect(url_for("admin_registrations"))

    return render_template("admin_reg_form.html", reg=None, action="add")


@app.route("/admin/registrations/<int:rid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_registration(rid):
    conn = get_db()
    reg  = conn.execute(
        "SELECT * FROM vehicle_registrations WHERE id=?", (rid,)
    ).fetchone()
    if not reg:
        conn.close()
        flash("Registration not found.", "error")
        return redirect(url_for("admin_registrations"))

    if request.method == "POST":
        f = request.form
        conn.execute("""
            UPDATE vehicle_registrations SET
              owner_name=?, email=?, phone=?, address=?,
              vehicle_make=?, vehicle_model=?, vehicle_color=?, vehicle_year=?,
              rc_number=?, registration_date=?, validity_date=?,
              insurance_validity=?, fitness_validity=?, tax_validity=?,
              dl_number=?, updated_at=?
            WHERE id=?
        """, (
            f.get("owner_name",""), f.get("email",""),
            f.get("phone",""), f.get("address",""),
            f.get("vehicle_make",""), f.get("vehicle_model",""),
            f.get("vehicle_color",""), int(f.get("vehicle_year",0) or 0),
            f.get("rc_number",""), f.get("registration_date",""),
            f.get("validity_date",""), f.get("insurance_validity",""),
            f.get("fitness_validity",""), f.get("tax_validity",""),
            f.get("dl_number",""), int(time.time()),
            rid,
        ))
        conn.commit()
        conn.close()
        flash("Registration updated.", "success")
        return redirect(url_for("admin_registrations"))

    conn.close()
    return render_template("admin_reg_form.html", reg=reg, action="edit")


@app.route("/admin/registrations/<int:rid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_registration(rid):
    conn = get_db()
    conn.execute("DELETE FROM vehicle_registrations WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    flash("Registration deleted.", "success")
    return redirect(url_for("admin_registrations"))


# ─── Admin: Users ─────────────────────────────────────────────────────────────

@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    conn  = get_db()
    users = conn.execute(
        "SELECT * FROM users ORDER BY role, username"
    ).fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
@login_required
@admin_required
def add_user():
    f    = request.form
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users
              (username,password,role,vehicle,phone,email,full_name)
            VALUES (?,?,?,?,?,?,?)
        """, (
            f.get("username","").strip(),
            f.get("password","").strip(),
            f.get("role","user"),
            f.get("vehicle","").strip().upper(),
            f.get("phone","").strip(),
            f.get("email","").strip(),
            f.get("full_name","").strip(),
        ))
        conn.commit()
        flash(f"User '{f.get('username')}' added.", "success")
    except sqlite3.IntegrityError:
        flash(f"Username '{f.get('username')}' already exists.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:uid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(uid):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    flash("User deleted.", "success")
    return redirect(url_for("admin_users"))


# ─── Admin: Export / Import CSV ───────────────────────────────────────────────

@app.route("/admin/export")
@login_required
@admin_required
def export_challans():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM challans ORDER BY timestamp DESC"
    ).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["ID","ChallanNo","Timestamp","VehicleType","Plate","Speed",
                "SpeedLimit","DateTime","Area","Image","Status",
                "FineAmount","PaidAt"])
    for r in rows:
        w.writerow(list(r))
    out.seek(0)
    return send_file(
        io.BytesIO(out.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"challans_{time.strftime('%Y%m%d')}.csv"
    )


# ─── Admin: Manual (Virtual) Challan ─────────────────────────────────────────

@app.route("/admin/manual-challan", methods=["GET", "POST"])
@login_required
@admin_required
def manual_challan():
    """Admin can create a challan manually by entering the plate number.
    Useful when OCR fails or video processing has an error."""
    conn = get_db()
    reg  = None
    plate_query = request.args.get("plate", "").strip().upper()

    if plate_query:
        reg = conn.execute(
            "SELECT * FROM vehicle_registrations WHERE plate=?", (plate_query,)
        ).fetchone()

    if request.method == "POST":
        f      = request.form
        plate  = f.get("plate", "").strip().upper()
        speed  = int(f.get("speed", 0) or 0)
        limit  = int(f.get("speed_limit", 60) or 60)
        area   = f.get("area", "Manual Entry").strip()
        vtype  = f.get("vehicle_type", "Car")
        note   = f.get("note", "").strip()

        if not plate:
            flash("Plate number is required.", "error")
            conn.close()
            return redirect(url_for("manual_challan"))

        # Fine calculation
        excess = speed - limit
        if excess <= 0:
            fine = 1000          # Minimum fine for manual entry
        elif excess <= 20:
            fine = 1000
        elif excess <= 40:
            fine = 2000
        else:
            fine = 5000

        challan_no = f"MCH{int(time.time())}{random.randint(100,999)}"
        dt_str     = time.strftime("%Y-%m-%d %H:%M:%S")

        c = conn.cursor()
        c.execute("""
            INSERT INTO challans
              (challan_no, timestamp, vehicle_type, plate, speed, speed_limit,
               datetime, area, image, status, fine_amount)
            VALUES (?,?,?,?,?,?,?,?,?,'Unpaid',?)
        """, (
            challan_no, int(time.time()), vtype, plate, speed, limit,
            dt_str, area,
            "",   # No image for manual challans
            fine,
        ))
        challan_id = c.lastrowid

        # In-app notification
        user = conn.execute(
            "SELECT id FROM users WHERE vehicle=?", (plate,)
        ).fetchone()
        if user:
            reason = f" Note: {note}" if note else ""
            msg = (f"⚠️ Manual challan #{challan_no} issued for {plate}. "
                   f"Speed: {speed} km/h in {area}. Fine: ₹{fine:,}.{reason}")
            conn.execute("""
                INSERT INTO notifications (user_id, plate, challan_id, message)
                VALUES (?,?,?,?)
            """, (user["id"], plate, challan_id, msg))

        conn.commit()

        # Track notification status for detailed feedback
        notify_status = {
            "owner_name": None,
            "phone": None, "sms_sent": False,
            "email": None, "email_sent": False,
            "no_record": False,
        }

        owner_row = conn.execute(
            "SELECT owner_name, phone, email FROM vehicle_registrations WHERE plate=?",
            (plate,)
        ).fetchone()
        if not owner_row:
            owner_row = conn.execute(
                "SELECT full_name as owner_name, phone, email FROM users WHERE vehicle=?",
                (plate,)
            ).fetchone()

        if owner_row:
            notify_status["owner_name"] = owner_row["owner_name"]
            notify_status["phone"]      = owner_row["phone"]
            notify_status["email"]      = owner_row["email"]
            if SMS_ENABLED:
                try:
                    if owner_row["phone"]:
                        r = send_challan_sms(owner_row["phone"], plate, speed,
                                             limit, area, challan_no, fine)
                        notify_status["sms_sent"] = bool(r)
                    if owner_row["email"]:
                        r = send_challan_email(owner_row["email"], plate, speed,
                                               limit, area, challan_no, fine)
                        notify_status["email_sent"] = bool(r)
                except Exception:
                    pass
        else:
            notify_status["no_record"] = True

        conn.close()

        import json as _json
        session["last_manual_challan"] = _json.dumps({
            "challan_no": challan_no,
            "plate":      plate,
            "fine":       fine,
            "notify":     notify_status,
        })
        flash(f"Manual challan {challan_no} created for {plate}.", "success")
        return redirect(url_for("manual_challan"))


    # GET — look up vehicle info if plate provided
    regs_all = conn.execute(
        "SELECT plate, owner_name FROM vehicle_registrations ORDER BY plate"
    ).fetchall()
    conn.close()
    return render_template(
        "manual_challan.html",
        reg=reg, plate_query=plate_query, regs_all=regs_all
    )


# ─── Admin: Import CSV ────────────────────────────────────────────────────────

@app.route("/admin/import-csv", methods=["GET", "POST"])
@login_required
@admin_required
def import_csv():
    results = None
    if request.method == "POST":
        file          = request.files.get("csv_file")
        default_limit = int(request.form.get("speed_limit", 60))
        area          = request.form.get("area", "Imported Zone").strip()

        if not file or not file.filename.endswith(".csv"):
            flash("Upload a valid .csv file.", "error")
            return redirect(url_for("import_csv"))

        stream = io.StringIO(
            file.stream.read().decode("utf-8", errors="ignore")
        )
        reader = csv.DictReader(stream)

        def col(row, *keys):
            for k in keys:
                for h in row:
                    if h.strip().lower() == k:
                        return str(row[h]).strip()
            return ""

        conn    = get_db()
        total   = violations = skipped = 0

        for raw in reader:
            row   = {k.strip().lower(): v for k, v in raw.items()}
            total += 1
            plate = col(row,"plate","vehicle_no","registration","number_plate","reg_no").upper()
            if not plate:
                skipped += 1; continue
            try:
                speed = int(float(col(row,"speed","detected_speed","speed_kmh") or 0))
            except ValueError:
                skipped += 1; continue
            try:
                limit = int(float(col(row,"speed_limit","limit","max_speed") or default_limit))
            except ValueError:
                limit = default_limit

            if speed <= limit:
                continue
            violations += 1
            vtype  = col(row,"vehicle_type","type","category") or "Car"
            dt     = col(row,"datetime","date_time","date","timestamp_str") or time.strftime("%Y-%m-%d %H:%M:%S")
            img    = col(row,"image","image_path","photo") or ""
            zone   = col(row,"area","location","zone") or area
            status = col(row,"status","payment_status") or "Unpaid"
            fine   = int((speed - limit) / 20) * 1000 + 1000

            conn.execute("""
                INSERT INTO challans
                  (challan_no,timestamp,vehicle_type,plate,speed,speed_limit,
                   datetime,area,image,status,fine_amount)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"CH{int(time.time())}{random.randint(100,999)}",
                int(time.time()), vtype, plate, speed, limit,
                dt, zone, img, status, fine,
            ))

        conn.commit()
        conn.close()
        results = {"total": total, "violations": violations, "skipped": skipped}
        flash(f"Import done: {violations} violations added.", "success")

    return render_template("import_csv.html", results=results)


# ─── Admin: Notifications ─────────────────────────────────────────────────────

@app.route("/admin/notifications")
@login_required
@admin_required
def admin_notifications():
    conn  = get_db()
    notifs = conn.execute("""
        SELECT n.*, u.username FROM notifications n
        LEFT JOIN users u ON n.user_id = u.id
        ORDER BY n.created_at DESC LIMIT 100
    """).fetchall()
    conn.close()
    return render_template("notifications.html", notifs=notifs, role="admin")


# ─── Admin: Notification Log (sent/failed SMS & Email) ───────────────────────

@app.route("/admin/notification-log")
@login_required
@admin_required
def notification_log():
    conn = get_db()
    # Create table if it doesn't exist yet
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            challan_id  TEXT,
            plate       TEXT,
            channel     TEXT,
            recipient   TEXT,
            status      TEXT,
            message     TEXT,
            error       TEXT DEFAULT '',
            sent_at     INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    logs = conn.execute(
        "SELECT * FROM notification_log ORDER BY id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template("notification_log.html", logs=logs)


@app.route("/admin/notification-log/resend/<int:lid>", methods=["POST"])
@login_required
@admin_required
def resend_notification(lid):
    """Re-send a failed/skipped notification."""
    conn = get_db()
    log = conn.execute(
        "SELECT * FROM notification_log WHERE id=?", (lid,)
    ).fetchone()
    conn.close()

    if not log:
        flash("Log entry not found.", "error")
        return redirect(url_for("notification_log"))

    # Fetch challan details
    conn = get_db()
    challan = conn.execute(
        "SELECT * FROM challans WHERE challan_no=?", (log["challan_id"],)
    ).fetchone()
    conn.close()

    if not challan:
        flash("Original challan not found.", "error")
        return redirect(url_for("notification_log"))

    if log["channel"] == "EMAIL":
        result = send_challan_email(
            log["recipient"], challan["plate"], challan["speed"],
            challan["speed_limit"], challan["area"],
            challan["challan_no"], challan["fine_amount"]
        )
    else:
        result = send_challan_sms(
            log["recipient"], challan["plate"], challan["speed"],
            challan["speed_limit"], challan["area"],
            challan["challan_no"], challan["fine_amount"]
        )

    if result:
        flash(f"Notification re-sent successfully to {log['recipient']}.", "success")
    else:
        flash(f"Re-send failed. Check your credentials in sms_service.py.", "error")

    return redirect(url_for("notification_log"))


# ─── User: Dashboard ──────────────────────────────────────────────────────────

@app.route("/user/dashboard")
@login_required
def user_dashboard():
    vehicle = session.get("vehicle", "")
    conn    = get_db()

    challans = conn.execute(
        "SELECT * FROM challans WHERE plate=? ORDER BY timestamp DESC",
        (vehicle,)
    ).fetchall()

    r = conn.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN status='Unpaid' THEN 1 ELSE 0 END),
               SUM(CASE WHEN status='Paid'   THEN 1 ELSE 0 END),
               MAX(speed),
               SUM(fine_amount),
               SUM(CASE WHEN status='Unpaid' THEN fine_amount ELSE 0 END)
        FROM challans WHERE plate=?
    """, (vehicle,)).fetchone()

    stats = {
        "total":       r[0] or 0,
        "unpaid":      r[1] or 0,
        "paid":        r[2] or 0,
        "max_speed":   r[3] or 0,
        "total_fine":  r[4] or 0,
        "pending_fine":r[5] or 0,
    }

    reg = conn.execute(
        "SELECT * FROM vehicle_registrations WHERE plate=?", (vehicle,)
    ).fetchone()

    conn.close()
    return render_template("user_dashboard.html",
                           challans=challans, stats=stats,
                           vehicle=vehicle, reg=reg)


@app.route("/user/challan/<int:cid>")
@login_required
def user_challan_detail(cid):
    vehicle = session.get("vehicle", "")
    conn    = get_db()
    challan = conn.execute(
        "SELECT * FROM challans WHERE id=? AND plate=?",
        (cid, vehicle)
    ).fetchone()
    if not challan:
        conn.close()
        flash("Challan not found.", "error")
        return redirect(url_for("user_dashboard"))
    conn.close()
    return render_template("user_challan_detail.html", challan=challan)


@app.route("/user/notifications")
@login_required
def user_notifications():
    uid  = session.get("user_id")
    conn = get_db()
    notifs = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC",
        (uid,)
    ).fetchall()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=?", (uid,)
    )
    conn.commit()
    conn.close()
    return render_template("notifications.html", notifs=notifs, role="user")


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
