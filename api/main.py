"""api/main.py — REFERENCE for Week 3 Lab Step 1.

The completed version. Wraps the W2 async pipeline behind a stable HTTP
contract (Question/Answer with field names question/content) while delegating
to the W2 pipeline internally.

Run with:
    uvicorn api.main:app --reload --port 8000

Hit with curl:
    curl -X POST http://localhost:8000/ask_batched \
         -H "Content-Type: application/json" \
         -d '{"question": "What is RAG?"}'
"""
import time
import asyncio
import logging

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# W2 pipeline — the underlying engine
from src.pipeline.pipeline import ask_llm as _pipeline_ask_llm
from src.pipeline.pipeline import Question as _PipelineQuestion

from src.pipeline.settings import RunSummary
from src.pipeline.store import connect, write_run, write_answers


logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public W3 API models — locked in ADR 0002
# These are intentionally separate from the W2 internal models (which use
# `text` field names). The endpoint handlers translate between the two.
# ─────────────────────────────────────────────────────────────────────────────
class Question(BaseModel):
    """Public request shape — locked in ADR 0002."""
    question: str


class Answer(BaseModel):
    """Public response shape — locked in ADR 0002."""
    content: str
    cost_usd: float
    retries: int


app = FastAPI(
    title="Capstone API",
    description="Wraps the W2 async pipeline. Contract locked in ADR 0002 (W3); internals upgraded W4+.",
    version="1.0.0",
)


def persist_answer(
    pipeline_ans,
    started_at: float,
    elapsed_seconds: float,
) -> None:
    """Persist one API request and its answer to SQLite."""

    summary = RunSummary(
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
        n_questions=1,
        n_succeeded=1,
        n_retries_total=pipeline_ans.retries,
        total_cost_usd=pipeline_ans.cost_usd,
        fail_rate=0.0,
        use_fake=True,
    )

    con = connect("results.db")

    try:
        run_id = write_run(con, summary)
        write_answers(con, run_id, [pipeline_ans])
    finally:
        con.close()

# ─────────────────────────────────────────────────────────────────────────────
# /ask_batched — non-streaming reference endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/ask_batched", response_model=Answer)
async def ask_batched(q: Question) -> Answer:
    """Non-streaming. Returns the full Answer in a single JSON body."""
    log.info("ask_batched  question=%r", q.question[:80])
    pipeline_q = _PipelineQuestion(text=q.question)
    pipeline_ans = await _pipeline_ask_llm(pipeline_q)
    return Answer(
        content=pipeline_ans.text,
        cost_usd=pipeline_ans.cost_usd,
        retries=pipeline_ans.retries,
    )


# ─────────────────────────────────────────────────────────────────────────────
# /health — liveness probe
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /ask — streaming endpoint (the contracted one)
# ─────────────────────────────────────────────────────────────────────────────
async def stream_answer(question_text: str):
    """Async generator yielding the answer word-by-word."""

    started_at = time.time()

    pipeline_q = _PipelineQuestion(text=question_text)
    pipeline_ans = await _pipeline_ask_llm(pipeline_q)

    elapsed_seconds = time.time() - started_at

    persist_answer(
        pipeline_ans,
        started_at,
        elapsed_seconds,
    )

    for word in pipeline_ans.text.split(" "):
        yield word + " "
        await asyncio.sleep(0.05)


@app.post("/ask")
async def ask(q: Question):
    """Streaming /ask — the contracted endpoint."""
    log.info("ask  question=%r", q.question[:80])
    return StreamingResponse(
        stream_answer(q.question),
        media_type="text/plain",
    )
