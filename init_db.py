"""
init_db.py — Enhanced Database Initialization
================================================
Tables:
  users                  → login credentials + contact info
  vehicle_registrations  → RC details, validity, owner info
  challans               → overspeed violation records + image path
  notifications          → in-app alerts for users
"""

import sqlite3
import time
import os

DB_PATH = "database.db"


def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── Users ──────────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT UNIQUE NOT NULL,
        password    TEXT NOT NULL,
        role        TEXT NOT NULL DEFAULT 'user',
        vehicle     TEXT DEFAULT '',
        phone       TEXT DEFAULT '',
        email       TEXT DEFAULT '',
        full_name   TEXT DEFAULT '',
        created_at  INTEGER DEFAULT (strftime('%s','now'))
    )""")

    # ── Vehicle Registrations ──────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_registrations (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        plate               TEXT UNIQUE NOT NULL,
        owner_name          TEXT NOT NULL,
        email               TEXT DEFAULT '',
        phone               TEXT DEFAULT '',
        address             TEXT DEFAULT '',
        vehicle_make        TEXT DEFAULT '',
        vehicle_model       TEXT DEFAULT '',
        vehicle_color       TEXT DEFAULT '',
        vehicle_year        INTEGER DEFAULT 0,
        rc_number           TEXT DEFAULT '',
        registration_date   TEXT DEFAULT '',
        validity_date       TEXT DEFAULT '',
        insurance_validity  TEXT DEFAULT '',
        fitness_validity    TEXT DEFAULT '',
        tax_validity        TEXT DEFAULT '',
        dl_number           TEXT DEFAULT '',
        updated_at          INTEGER DEFAULT (strftime('%s','now'))
    )""")

    # ── Challans ───────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS challans (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        challan_no    TEXT DEFAULT '',
        timestamp     INTEGER,
        vehicle_type  TEXT DEFAULT 'Car',
        plate         TEXT,
        speed         INTEGER,
        speed_limit   INTEGER DEFAULT 60,
        datetime      TEXT,
        area          TEXT,
        image         TEXT DEFAULT '',
        status        TEXT DEFAULT 'Unpaid',
        fine_amount   INTEGER DEFAULT 2000,
        paid_at       TEXT DEFAULT NULL,
        payment_ref   TEXT DEFAULT ''
    )""")

    # ── Notifications ──────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        plate       TEXT,
        challan_id  INTEGER,
        message     TEXT,
        is_read     INTEGER DEFAULT 0,
        created_at  INTEGER DEFAULT (strftime('%s','now')),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    # ── Seed: Admin ────────────────────────────────────────────────────────────
    c.execute("""
    INSERT OR IGNORE INTO users (username,password,role,vehicle,phone,email,full_name)
    VALUES ('admin','admin123','admin','','+919999999999',
            'admin@traffic.rajasthan.gov.in','Traffic Administrator')
    """)

    # ── Seed: Users ────────────────────────────────────────────────────────────
    users = [
        ('user1','user123','user','RJ14AB1234','+911234567890',
         'bagravishal7781@gmail.com','Rajesh Kumar'),
        ('user2','user123','user','RJ14CD5678','+910987654321',
         'yash.sngh060205@gmail.com','Priya Sharma'),
        ('user3','user123','user','RJ14EF9012','+919876543210',
         'shubhampanchal362002@gmail.com','Amit Singh'),
    ]
    for u in users:
        c.execute("""
        INSERT OR IGNORE INTO users
          (username,password,role,vehicle,phone,email,full_name)
        VALUES (?,?,?,?,?,?,?)""", u)

    # ── Seed: Vehicle Registrations ────────────────────────────────────────────
    regs = [
        ('RJ14AB1234','Rajesh Kumar','bagravishal7781@gmail.com','+911234567890',
         '45, Sindhi Colony, Jaipur, Rajasthan - 302004',
         'Maruti Suzuki','Swift Dzire','White',2020,
         'RJ14/2020/001234','2020-03-15','2035-03-14',
         '2026-03-14','2026-03-14','2026-03-14','RJ0420120001234'),

        ('RJ14CD5678','Priya Sharma','yash.sngh060205@gmail.com','+910987654321',
         '12, Vaishali Nagar, Jaipur, Rajasthan - 302021',
         'Honda','City','Silver',2021,
         'RJ14/2021/005678','2021-06-20','2036-06-19',
         '2026-06-19','2026-06-19','2026-06-19','RJ0421120005678'),

        ('RJ14EF9012','Amit Singh','shubhampanchal362002@gmail.com','+919876543210',
         '78, Mansarovar, Jaipur, Rajasthan - 302020',
         'Hyundai','Creta','Black',2022,
         'RJ14/2022/009012','2022-01-10','2037-01-09',
         '2024-01-09','2026-01-09','2026-01-09','RJ0422120009012'),

        ('RJ14GH3456','Vikram Mehta','vikram.mehta@gmail.com','+918765432109',
         '22, Raja Park, Jaipur, Rajasthan - 302004',
         'Toyota','Innova Crysta','Grey',2019,
         'RJ14/2019/003456','2019-09-05','2034-09-04',
         '2025-09-04','2024-09-04','2025-09-04','RJ0419120003456'),
    ]
    for r in regs:
        c.execute("""
        INSERT OR IGNORE INTO vehicle_registrations
          (plate,owner_name,email,phone,address,vehicle_make,vehicle_model,
           vehicle_color,vehicle_year,rc_number,registration_date,validity_date,
           insurance_validity,fitness_validity,tax_validity,dl_number)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", r)

    # ── Seed: Sample Challans ──────────────────────────────────────────────────
    now = int(time.time())
    challans = [
        (f'CH{now}001', now - 86400,  'Car',  'RJ14AB1234', 85,  60,
         '2025-01-15 10:30:00','Ajmer Road, Jaipur',   '', 'Unpaid', 2000),
        (f'CH{now}002', now - 172800, 'Car',  'RJ14CD5678', 95,  60,
         '2025-01-14 14:20:00','Tonk Road, Jaipur',    '', 'Paid',   2000),
        (f'CH{now}003', now - 259200, 'Car',  'RJ14EF9012', 125, 60,
         '2025-01-13 09:15:00','Sikar Road, Jaipur',   '', 'Unpaid', 5000),
        (f'CH{now}004', now - 345600, 'Car',  'RJ14GH3456', 78,  60,
         '2025-01-12 17:45:00','Agra Road, Jaipur',    '', 'Unpaid', 2000),
        (f'CH{now}005', now - 432000, 'Car',  'RJ14AB1234', 72,  60,
         '2025-01-11 08:00:00','JLN Marg, Jaipur',     '', 'Paid',   2000),
        (f'CH{now}006', now - 518400, 'Bike', 'RJ14CD5678', 110, 60,
         '2025-01-10 11:30:00','MI Road, Jaipur',      '', 'Unpaid', 5000),
    ]
    for ch in challans:
        c.execute("""
        INSERT OR IGNORE INTO challans
          (challan_no,timestamp,vehicle_type,plate,speed,speed_limit,
           datetime,area,image,status,fine_amount)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", ch)

    conn.commit()
    conn.close()
    print("✅  Database initialized.")
    print("    admin  → admin / admin123")
    print("    user1  → user1 / user123  | RJ14AB1234")
    print("    user2  → user2 / user123  | RJ14CD5678")
    print("    user3  → user3 / user123  | RJ14EF9012")


if __name__ == "__main__":
    init_database()
