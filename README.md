# 🚓 Smart Traffic E-Challan System

A full-stack traffic enforcement system with AI-powered vehicle detection, automatic challan generation, and a modern web portal.

---

## Features

### Detection (`main.py`)
- YOLOv8 real-time vehicle detection
- Multi-object centroid tracker with persistent IDs
- Speed estimation via dual reference lines
- EasyOCR number plate recognition (CLAHE pre-processed)
- **Vehicle image capture** at moment of violation
- Tiered fine calculation (₹1000 / ₹2000 / ₹5000)
- Auto-challan saved to DB with captured image path
- SMS + HTML email notification to registered owner
- Red flash alert overlay on violation

### Web Portal (`app.py`)
**Admin Dashboard**
- Live stats: total/unpaid/paid, revenue, avg/max speed, vehicle type counts
- Filter challans by status, area, plate, date
- Captured vehicle thumbnail per challan row
- **Vehicle Info Modal** — click car icon on any row → AJAX popup with full owner details
- **Full Vehicle Profile page** — registration, RC, insurance, fitness, tax validity cards
- Inline status toggle (Unpaid ↔ Paid) without page reload
- Edit / delete individual challans
- CSV export & flexible CSV import

**User Dashboard**
- Personal challan cards with captured vehicle photos
- Pending fine alert banner
- Vehicle registration card with validity pills
- Pay Now button (portal-ready)

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Initialise database
python init_db.py

# 3. Start web portal
python app.py
# → http://localhost:5000

# 4. Run detection (separate terminal)
python main.py --source cars.mp4
```

---

## Default Credentials

| Role  | Username | Password | Vehicle     |
|-------|----------|----------|-------------|
| Admin | admin    | admin123 | —           |
| User  | user1    | user123  | RJ14AB1234  |
| User  | user2    | user123  | RJ14CD5678  |
| User  | user3    | user123  | RJ14EF9012  |

---

## Project Structure

```
traffic_system/
├── main.py                   ← YOLOv8 detection + challan creation
├── app.py                    ← Flask web portal
├── init_db.py                ← DB init + seed data
├── tracker.py                ← Centroid multi-object tracker
├── sms_service.py            ← Twilio SMS + SMTP email
├── requirements.txt
├── database.db               ← SQLite (auto-created)
├── static/
│   └── captures/             ← Vehicle images saved here
└── templates/
    ├── base.html
    ├── login.html
    ├── admin_dashboard.html
    ├── admin_vehicle_details.html
    ├── admin_registrations.html
    ├── admin_reg_form.html
    ├── admin_users.html
    ├── edit_challan.html
    ├── import_csv.html
    ├── notifications.html
    ├── user_dashboard.html
    └── user_challan_detail.html
```

---

## Fine Structure

| Excess Speed  | Fine    |
|---------------|---------|
| Up to +20 km/h | ₹1,000 |
| +21 to +40 km/h | ₹2,000 |
| Above +40 km/h | ₹5,000 |

---

## SMS / Email Config

Edit `sms_service.py` or set environment variables:

```
TWILIO_SID    = ACxxxxxxxx...
TWILIO_TOKEN  = your_auth_token
TWILIO_FROM   = +1XXXXXXXXXX
SMTP_HOST     = smtp.gmail.com
SMTP_PORT     = 587
SMTP_USER     = your@gmail.com
SMTP_PASS     = your_app_password
```
