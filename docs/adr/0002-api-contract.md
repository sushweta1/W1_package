```

Response:

Streaming plain text response.

The `/ask` endpoint uses the Week 2 pipeline internally and streams the generated answer word-by-word.

### POST `/ask_batched`

Request:

```json
{
  "question": "What is RAG?"
}
```

Response:

```json
{
  "content": "RAG combines retrieval with generation.",
  "cost_usd": 0.0,
  "retries": 0
}
```

### GET `/health`

Response:

```json
{
  "status": "ok"
}
```

## Public Models

### Question

- `question: str`

### Answer

- `content: str`
- `cost_usd: float`
- `retries: int`

## Internal Mapping

The Week 3 API translates between the public API models and the Week 2 internal pipeline models.

- Public `question` maps to the Week 2 internal `text` field.
- Week 2 answer `text` maps to the public `content` field.

This keeps the external API contract independent of the internal pipeline representation.

## Persistence

Successful `/ask` requests are persisted using the Week 2 SQLite persistence layer in `src/pipeline/store.py`.

Each successful request creates:

- one row in `runs`
- one corresponding row in `answers`

`answers.run_id` is linked to `runs.id` through a foreign key.

The persistence layer was tested with 50 requests at up to 10 concurrent requests. All 50 requests succeeded and all 50 were persisted.

## Consequences

- Clients depend on a stable Week 3 API contract.
- Internal pipeline implementation can evolve without changing the public field names.
- FastAPI/Pydantic validates incoming requests.
- `/ask` provides streaming output while `/ask_batched` provides a normal JSON response.
- The existing Week 2 SQLite persistence layer is reused for successful `/ask` requests.