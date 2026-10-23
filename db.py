"""db.py - SQLite storage. Only numbers, checks and explanations are saved. NEVER the photo."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/billsaathi.db")


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, created_at TEXT, model TEXT,
        extracted TEXT, checks TEXT, explanations TEXT)""")
    return conn


def save_analysis(title, model, extracted, checks):
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO analyses (title, created_at, model, extracted, checks, explanations) VALUES (?,?,?,?,?,?)",
            (title, datetime.now().strftime("%Y-%m-%d %H:%M"), model,
             json.dumps(extracted, ensure_ascii=False), json.dumps(checks, ensure_ascii=False), "{}"))
        return cur.lastrowid


def list_analyses():
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, title, created_at FROM analyses ORDER BY id DESC")]


def get_analysis(analysis_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    for key in ("extracted", "checks", "explanations"):
        item[key] = json.loads(item[key] or "{}")
    return item


def save_explanation(analysis_id, language, explanation):
    item = get_analysis(analysis_id)
    if item is None:
        return
    item["explanations"][language] = explanation
    with _connect() as conn:
        conn.execute("UPDATE analyses SET explanations=? WHERE id=?",
                     (json.dumps(item["explanations"], ensure_ascii=False), analysis_id))


def delete_analysis(analysis_id):
    with _connect() as conn:
        conn.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))