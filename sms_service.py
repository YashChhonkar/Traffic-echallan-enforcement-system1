"""
sms_service.py — Notification Service (Email + SMS)
=====================================================
EMAIL : Gmail SMTP  (free — just needs App Password)
SMS   : Fast2SMS API (free tier, Indian numbers)

SETUP STEPS:
  1. Gmail:
     - Go to myaccount.google.com → Security → 2-Step Verification → ON
     - Then go to: myaccount.google.com/apppasswords
     - Create app password → copy the 16-char password
     - Set SMTP_USER and SMTP_PASSWORD below

  2. Fast2SMS (free SMS for Indian numbers):
     - Register at fast2sms.com
     - Go to Dev API → copy your API key
     - Set FAST2SMS_API_KEY below
"""

import os
import smtplib
import sqlite3
import time
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── CONFIG — Fill these in ───────────────────────────────────────────────────

# Gmail SMTP
SMTP_USER     = "karansharmaa089@gmail.com"
SMTP_PASSWORD = "ddffnewaovybgpna"
SMTP_FROM     = f"Traffic E-Challan Jaipur <{SMTP_USER}>"

# Fast2SMS API (free for Indian numbers)
FAST2SMS_API_KEY = "bQKt4PUTi5SwHvcRfIVkEqhF20W83eZp6jBdnsYJAyG9NMLurzfoxFmpE3wejXs9G80yrukUqLKHA1BW"

DB_PATH = "database.db"

# ─── Notification Log (saves every attempt to DB) ─────────────────────────────

def _log_notification(challan_id, plate, channel, recipient, status, message, error=""):
    """Save every notification attempt to notification_log table."""
    try:
        conn = sqlite3.connect(DB_PATH)
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
        conn.execute("""
            INSERT INTO notification_log
              (challan_id, plate, channel, recipient, status, message, error)
            VALUES (?,?,?,?,?,?,?)
        """, (str(challan_id), plate, channel, recipient, status, message, error))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[LOG ERROR] {e}")


# ─── Phone Formatter ──────────────────────────────────────────────────────────

def _clean_phone(phone: str) -> str:
    """Return 10-digit Indian mobile number."""
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if phone.startswith("+91"):
        phone = phone[3:]
    elif phone.startswith("91") and len(phone) == 12:
        phone = phone[2:]
    return phone


# ─── EMAIL ────────────────────────────────────────────────────────────────────

def send_challan_email(to_email, plate, speed, speed_limit, area,
                       challan_no, fine_amount):
    """Send HTML challan email via Gmail SMTP."""

    if "your_gmail" in SMTP_USER or not SMTP_USER:
        print("[EMAIL] Gmail not configured — skipping")
        _log_notification(challan_no, plate, "EMAIL", to_email,
                          "SKIPPED", f"Challan {challan_no} for {plate}",
                          "Gmail credentials not set in sms_service.py")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🚨 Traffic E-Challan Notice — {challan_no}"
        msg["From"]    = SMTP_FROM
        msg["To"]      = to_email

        html = f"""
        <html>
        <body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f2f4f8">
          <div style="max-width:600px;margin:30px auto;background:white;
                      border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,.12)">

            <!-- Header -->
            <div style="background:linear-gradient(135deg,#c0392b,#8e1a0e);
                        padding:28px 30px;text-align:center">
              <div style="font-size:2rem;margin-bottom:6px">🚨</div>
              <h2 style="color:white;margin:0;font-size:1.4rem;letter-spacing:.5px">
                Traffic E-Challan Notice
              </h2>
              <div style="color:rgba(255,255,255,.75);font-size:.85rem;margin-top:4px">
                Rajasthan Traffic Police
              </div>
            </div>

            <!-- Challan No Banner -->
            <div style="background:#fff3cd;padding:14px 30px;text-align:center;
                        border-bottom:2px solid #f4a823">
              <div style="font-size:.75rem;color:#888;letter-spacing:.5px">CHALLAN NUMBER</div>
              <div style="font-family:monospace;font-size:1.3rem;font-weight:800;
                          color:#0f1e3d;margin-top:2px">{challan_no}</div>
            </div>

            <!-- Details Table -->
            <div style="padding:28px 30px">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;font-size:.9rem">
                <tr>
                  <td style="padding:12px 0;border-bottom:1px solid #f0f2f5;
                              color:#888;width:45%">🚗 Vehicle Plate</td>
                  <td style="padding:12px 0;border-bottom:1px solid #f0f2f5;
                              font-weight:700;font-family:monospace;color:#0f1e3d">{plate}</td>
                </tr>
                <tr>
                  <td style="padding:12px 0;border-bottom:1px solid #f0f2f5;color:#888">
                    💨 Detected Speed</td>
                  <td style="padding:12px 0;border-bottom:1px solid #f0f2f5">
                    <span style="color:#e63946;font-weight:800;font-size:1.1rem">
                      {speed} km/h
                    </span>
                    <span style="color:#aaa;font-size:.8rem">
                      (Limit: {speed_limit} km/h | Excess: +{speed - speed_limit} km/h)
                    </span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 0;border-bottom:1px solid #f0f2f5;color:#888">
                    📍 Location</td>
                  <td style="padding:12px 0;border-bottom:1px solid #f0f2f5;font-weight:600">
                    {area}</td>
                </tr>
                <tr>
                  <td style="padding:12px 0;color:#888">💰 Fine Amount</td>
                  <td style="padding:12px 0">
                    <span style="color:#c0392b;font-size:1.4rem;font-weight:800">
                      ₹{fine_amount:,}
                    </span>
                  </td>
                </tr>
              </table>

              <!-- Warning -->
              <div style="margin-top:22px;padding:14px 18px;background:#fff0f0;
                          border-radius:8px;border-left:4px solid #e63946;font-size:.85rem">
                <strong>⚠️ Important Notice:</strong> Please pay the fine within
                <strong>30 days</strong> to avoid legal proceedings and suspension
                of driving licence.
              </div>

              <!-- Pay Button -->
              <div style="text-align:center;margin-top:24px">
                <a href="http://traffic.rajasthan.gov.in/pay"
                   style="background:#c0392b;color:white;padding:13px 36px;
                          border-radius:8px;text-decoration:none;font-weight:700;
                          font-size:.95rem;display:inline-block">
                  Pay Fine Online →
                </a>
              </div>
            </div>

            <!-- Footer -->
            <div style="background:#f8f9ff;padding:16px 30px;text-align:center;
                        font-size:.75rem;color:#aaa;border-top:1px solid #eee">
              Rajasthan Traffic Police &nbsp;|&nbsp; traffic.rajasthan.gov.in
              &nbsp;|&nbsp; Helpline: 1800-180-6030
              <br>This is an automated message. Do not reply.
            </div>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASSWORD)
            srv.sendmail(SMTP_FROM, to_email, msg.as_string())

        print(f"[EMAIL ✓] Sent to {to_email}")
        _log_notification(challan_no, plate, "EMAIL", to_email,
                          "SENT", f"Challan {challan_no} | {speed}km/h | Rs.{fine_amount}")
        return True

    except Exception as e:
        print(f"[EMAIL ✗] {e}")
        _log_notification(challan_no, plate, "EMAIL", to_email,
                          "FAILED", f"Challan {challan_no}", str(e))
        return False


# ─── SMS via Fast2SMS ─────────────────────────────────────────────────────────

def send_challan_sms(to_phone, plate, speed, speed_limit, area,
                     challan_no, fine_amount):
    """Send SMS via Fast2SMS API (free tier, Indian numbers)."""

    if "your_fast2sms" in FAST2SMS_API_KEY or not FAST2SMS_API_KEY:
        print("[SMS] Fast2SMS not configured — skipping")
        _log_notification(challan_no, plate, "SMS", to_phone,
                          "SKIPPED", f"Challan {challan_no} for {plate}",
                          "Fast2SMS API key not set in sms_service.py")
        return False

    phone = _clean_phone(to_phone)
    message = (
        f"TRAFFIC CHALLAN NOTICE\n"
        f"Challan: {challan_no}\n"
        f"Vehicle: {plate}\n"
        f"Speed: {speed} km/h (Limit: {speed_limit})\n"
        f"Location: {area}\n"
        f"Fine: Rs.{fine_amount}\n"
        f"Pay within 30 days. Helpline: 1800-180-6030"
    )

    try:
        resp = requests.post(
            "https://www.fast2sms.com/dev/bulkV2",
            headers={"authorization": FAST2SMS_API_KEY},
            data={
                "route":   "v3",
                "sender_id": "TXTIND",
                "message": message,
                "language": "english",
                "numbers": phone,
            },
            timeout=10
        )
        data = resp.json()
        if data.get("return") is True:
            print(f"[SMS ✓] Sent to {phone}")
            _log_notification(challan_no, plate, "SMS", phone,
                              "SENT", message)
            return True
        else:
            err = str(data)
            print(f"[SMS ✗] {err}")
            _log_notification(challan_no, plate, "SMS", phone,
                              "FAILED", message, err)
            return False

    except Exception as e:
        print(f"[SMS ✗] {e}")
        _log_notification(challan_no, plate, "SMS", phone,
                          "FAILED", message, str(e))
        return False


def send_payment_confirmation_sms(to_phone, plate, challan_id):
    """Send payment confirmation SMS."""
    if "your_fast2sms" in FAST2SMS_API_KEY or not FAST2SMS_API_KEY:
        return False
    phone   = _clean_phone(to_phone)
    message = (
        f"PAYMENT CONFIRMED\n"
        f"Vehicle: {plate} | Challan #{challan_id}\n"
        f"Status: PAID\n"
        f"Thank you — Traffic Police, Rajasthan"
    )
    try:
        resp = requests.post(
            "https://www.fast2sms.com/dev/bulkV2",
            headers={"authorization": FAST2SMS_API_KEY},
            data={"route": "v3", "sender_id": "TXTIND",
                  "message": message, "language": "english", "numbers": phone},
            timeout=10
        )
        return resp.json().get("return") is True
    except Exception:
        return False
