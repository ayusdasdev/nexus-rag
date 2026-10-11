# ADR-0013: Observability: JSON logs, request traces and query traces (M9)

Date: 2026-10-11
Status: accepted

## Context
M9 (guide 9.1) asks that any chat answer can be reconstructed after the fact, and that
feedback can attach to it. Before this the API logged plain text with a request id only;
retrieval timed its own stages, and nothing about an answer was kept except a conversation's
messages. `/v1/chat` answers left nothing at all.

Questions and answers are tenant data, and documents must never reach application logs.

## Decision
- **Stdlib only, no new dependency (your choice).**
  - `app/core/logging.py` writes one JSON object per line: `ts`, `level`, `logger`, `message`,
    `request_id`, `tenant_id`, and a whitelist of extras (`stage`, `ms`, ids, counts).
  - `app/core/tracing.py` keeps one request-scoped trace in a context variable, started by
    the request-id middleware. It has `with span(name):` and `record(name, ms)`, in
    OpenTelemetry's vocabulary but without its SDK.
  - Uvicorn's loggers and the Celery worker use the same JSON format.
- **Tenant in logs:** set only by `get_current_user` after the token is verified, and reset
  per request. Worker lines carry no tenant (per-task context would risk leaking between
  tasks).
- **Exceptions in logs:** type plus `file:line in function` frames only. The message (which
  can echo prompt or document text) and source lines (which can quote literals) are never
  written; a test checks a secret raised in an exception never reaches the log. This extends
  the existing "errors by type only" rule.
- **Spans:** every retrieval stage (through its existing stage timings), the follow-up
  rewrite, time to first token, and generation (model, source count, estimated tokens).
- **Query traces** (`query_traces`, migration `c29cb20a16dd`): one row per `/v1/chat` answer
  and per conversation turn, written however the stream ends (done, error, client gone).
  - It holds the question, rewritten query and answer **(your choice: text is kept)**.
  - Retrieval is stored as top-20 chunk ids, scores and ranks per stage plus the final items,
    **never chunk text** (tested).
  - It also holds latency per span, model, error code, and token counts estimated as
    characters / 4 (the context budget's estimate; providers don't report usage here).
  - `est_cost` is null on the free local stack.
  - A failed write is logged by type and never breaks an answer.
- **Retention: 30 days (your choice), `TRACE_RETENTION_DAYS`.** Writing a trace deletes that
  tenant's expired traces; `trace_repository.purge_expired` does every tenant for a periodic
  job. A trace is deleted with its conversation message (FK cascade). Its user is tied to its
  tenant by a composite FK.
- **Access:**
  - `GET /v1/traces/{request_id}` is for admins of the trace's tenant only (your choice,
    matching ADR-0005 for retrieval internals). Members and other tenants get the same 404 as
    a missing trace. A reused request id returns the newest trace.
  - `POST /v1/messages/{id}/feedback` takes -1 or 1, and only on the caller's own assistant
    message; anything else is 404. `/v1/chat` answers have no message, so no feedback.

## Alternatives considered
- OpenTelemetry SDK plus FastAPI instrumentation: standard exporters, but 3-5 new packages
  and nothing here to export to without running a collector. The query trace table would
  still be needed.
- Ids and sizes only in traces: more private, but "show me request abc" couldn't show what
  was asked or answered.
- Own traces readable by every user: more useful for users, but it exposes retrieval
  internals beyond ADR-0005's admin-only rule.

## Consequences
- **Debugging:** a bad answer can be replayed from its `X-Request-ID`: the question, where
  each candidate ranked at each stage, timings and the answer.
- **Privacy:**
  - Traces are tenant data with a 30-day life, and admins of the tenant can read members'
    questions and answers.
  - Deleting a document does not delete the answers that quoted it, within retention (as with
    messages, ADR-0009).
  - A tenant with no new answers keeps its expired traces until a global purge runs; nothing
    schedules that yet (a cron or Celery beat is needed).
- **Token counts** are estimates, not provider-reported usage.
