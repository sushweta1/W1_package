"""pipeline.py — Week 2 hands-on starter.

We'll fill in the TODOs together during the live session. The pieces:

    Step 2 — async def ask_llm                 (one call)
    Step 3 — ask_llm_with_retry                (exponential backoff)
    Step 4 — run_batch with asyncio.gather     (parallel fan-out)
    Step 5 — JSON-formatted structured logging

For the live demo we call ``fake_ask_llm`` from ``fake_llm.py`` —
no API quota, no network flakiness, and a ``fail_rate`` knob so retries
fire on demand. In the lab you'll swap to the real ``AsyncOpenAI`` client
(same ``Question``/``Answer`` shape — only one import changes).

Run it (after the TODOs are filled):
    python pipeline.py           # fail_rate = 0.0  (clean parallel run)
    python pipeline.py 0.4       # fail_rate = 0.4  (forces retries)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import csv
import argparse
from pathlib import Path


from .settings import Settings, RunSummary
from .logging_config import get_logger
from .fake_llm import fake_ask_llm

log = get_logger()

_settings_for_import = Settings()

if _settings_for_import.use_fake:
    from .fake_llm import Question, Answer, fake_ask_llm, FakeLLMError
else:
    from dotenv import load_dotenv
    from openai import AsyncOpenAI
    from pydantic import BaseModel

    load_dotenv()
    _client = None

    class Question(BaseModel):
        text: str

    class Answer(BaseModel):
        question: str
        text: str
        cost_usd: float
        retries: int = 0

def load_questions(
    path: str | Path = "data/questions.csv",
) -> list[Question]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    return [
        Question(text=row["text"])
        for row in rows
        if row.get("text")
    ]

def summarise_run(
    answers: list[Answer],
    *,
    started_at: float,
    elapsed: float,
    fail_rate: float,
    use_fake: bool,
) -> RunSummary:
    return RunSummary(
        started_at=started_at,
        elapsed_seconds=elapsed,
        n_questions=len(answers),
        n_succeeded=len(answers),
        n_retries_total=sum(a.retries for a in answers),
        total_cost_usd=sum(a.cost_usd for a in answers),
        fail_rate=fail_rate,
        use_fake=use_fake,
    )

# ---------- Step 2: one async call ----------
async def ask_llm(q: Question, fail_rate: float = 0.0) -> Answer:
    """One call. Fake or real depending on Settings.use_fake."""

    if _settings_for_import.use_fake:
        ans = await fake_ask_llm(q, fail_rate=fail_rate)
    else:
        global _client

        if _client is None:
            _client = AsyncOpenAI()

        resp = await _client.chat.completions.create(
            model=_settings_for_import.model,
            messages=[{"role": "user", "content": q.text}],
        )

        ans = Answer(
            question=q.text,
            text=resp.choices[0].message.content,
            cost_usd=0.0001,
        )

    log.info(f"asked: {q.text[:40]}")
    return ans
    


# ---------- Step 3: retry with exponential backoff ----------
async def ask_llm_with_retry(
    q: Question, tries: int = 3, fail_rate: float = 0.0
) -> Answer:
    """Retry up to ``tries`` times. Wait 1 s, 2 s, 4 s between attempts."""

    for attempt in range(tries):
        try:
            ans = await ask_llm(q, fail_rate=fail_rate)
            ans.retries = attempt
            return ans
        except Exception as exc:
            if attempt == tries - 1:
                raise

            log.warning(
                f"retry {attempt + 1} for: {q.text[:40]} ({exc})"
            )

    await asyncio.sleep(2 ** attempt)

    raise RuntimeError("Retry loop exited unexpectedly")


# ---------- Step 4: gather it all together ----------
async def run_batch(
    questions: list[Question], fail_rate: float = 0.0
) -> list[Answer]:
    """Fire all questions in parallel via ``asyncio.gather``."""

    tasks = [ask_llm_with_retry(q, fail_rate=fail_rate) for q in questions]
    return await asyncio.gather(*tasks)


async def run_in_batches(
    questions: list[Question],
    batch_size: int = 5,
    fail_rate: float = 0.0,
) -> list[Answer]:
    out: list[Answer] = []

    for i in range(0, len(questions), batch_size):
        chunk = questions[i : i + batch_size]

        log.info(
            f"batch {i // batch_size + 1}: {len(chunk)} questions"
        )

        batch_answers = await asyncio.gather(
            *(
                ask_llm_with_retry(q, fail_rate=fail_rate)
                for q in chunk
            )
        )

        out.extend(batch_answers)

        await asyncio.sleep(0.1)

    return out

# ---------- Step 5: structured (JSON) logging ----------



# ---------- main ----------
if __name__ == "__main__":
    from .store import connect, write_run, write_answers
    settings = Settings()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N questions",
    )
    args = parser.parse_args()

    questions = load_questions(settings.questions_csv)

    if args.limit is not None:
        questions = questions[:args.limit]

    log.info(f"loaded {len(questions)} questions")

    started = time.time()

    answers = asyncio.run(
        run_in_batches(
            questions,
            batch_size=settings.batch_size,
            fail_rate=settings.fail_rate,
        )
    )

    elapsed = time.time() - started

    summary = summarise_run(
        answers,
        started_at=started,
        elapsed=elapsed,
        fail_rate=settings.fail_rate,
        use_fake=settings.use_fake,
    )

    log.info(f"summary: {summary.model_dump_json()}")

    settings.results_json.write_text(
        json.dumps(
            {
                "summary": summary.model_dump(mode="json"),
                "answers": [a.model_dump() for a in answers],
            },
            indent=2,
        )
    )

    with connect(settings.results_db) as con:
        run_id = write_run(con, summary)
        n = write_answers(con, run_id, answers)

    log.info(
        f"persisted run {run_id} with {n} answers to {settings.results_db}"
    )

    print(
        f"wrote {len(answers)} answers to "
        f"{settings.results_json} in {elapsed:.2f}s"
    )
