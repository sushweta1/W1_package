import sqlite3
import time
from pathlib import Path
from typing import Iterable

from .pipeline import Answer
from .settings import RunSummary

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    elapsed_seconds REAL NOT NULL,
    n_questions INTEGER NOT NULL,
    n_succeeded INTEGER NOT NULL,
    n_retries_total INTEGER NOT NULL,
    total_cost_usd REAL NOT NULL,
    fail_rate REAL NOT NULL,
    use_fake INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    retries INTEGER NOT NULL DEFAULT 0,
    ts REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""

def connect(path: str | Path = "results.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    return con

def write_run(con: sqlite3.Connection, summary: RunSummary) -> int:
    cur = con.execute(
        """
        INSERT INTO runs (
            started_at,
            elapsed_seconds,
            n_questions,
            n_succeeded,
            n_retries_total,
            total_cost_usd,
            fail_rate,
            use_fake
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary.started_at,
            summary.elapsed_seconds,
            summary.n_questions,
            summary.n_succeeded,
            summary.n_retries_total,
            summary.total_cost_usd,
            summary.fail_rate,
            int(summary.use_fake),
        ),
    )
    con.commit()
    return cur.lastrowid

def write_answers(
    con: sqlite3.Connection,
    run_id: int,
    answers: Iterable[Answer],
) -> int:
    ts = time.time()

    rows = [
        (
            run_id,
            a.question,
            a.text,
            a.cost_usd,
            a.retries,
            ts,
        )
        for a in answers
    ]

    con.executemany(
        """
        INSERT INTO answers (
            run_id,
            question,
            answer,
            cost_usd,
            retries,
            ts
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    con.commit()
    return len(rows)