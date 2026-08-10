import sqlite3
from pathlib import Path
from typing import Dict, Optional, Any

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "crewai_jobs.db"


def init_db():
    """Initializes the SQLite job queue table (Explicitly disables WAL for NFS)."""
    with sqlite3.connect(_DB_PATH, timeout=60) as conn:
        # Explicitly enforce standard journal mode to prevent NFS lock crashes
        conn.execute("PRAGMA journal_mode=DELETE;")
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def create_job(job_id: str, question: str) -> Dict[str, Any]:
    with sqlite3.connect(_DB_PATH, timeout=60) as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, question, status) VALUES (?, ?, ?)",
            (job_id, question, "pending")
        )
        conn.commit()
    return {"job_id": job_id, "status": "pending"}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(_DB_PATH, timeout=60) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def fetch_next_pending_job() -> Optional[Dict[str, Any]]:
    with sqlite3.connect(_DB_PATH, timeout=60) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def update_job_status(job_id: str, status: str, result: Optional[str] = None, error: Optional[str] = None):
    with sqlite3.connect(_DB_PATH, timeout=60) as conn:
        conn.execute(
            """
            UPDATE jobs 
            SET status = ?, result = ?, error = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE job_id = ?
            """,
            (status, result, error, job_id)
        )
        conn.commit()


def cancel_job(job_id: str) -> bool:
    """
    Marks a job as 'cancelled' if it is currently 'pending' or 'processing'.
    Returns True if the job was found and updated, False otherwise.
    """
    with sqlite3.connect(_DB_PATH, timeout=60) as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP "
            "WHERE job_id = ? AND status IN ('pending', 'processing')",
            (job_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


