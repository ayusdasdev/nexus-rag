# ADR-0008: Chat SSE event schema

Date: 2026-10-09
Status: accepted

## Context
`POST /v1/chat` streams an answer as the model writes it. Clients need the sources first (to
render them), the text as it arrives, and a final, validated result. ADR-0007 also requires
that citations are checked against the chunks that were actually sent, and that links in the
answer are never fetched.

## Decision
- Server-Sent Events, `text/event-stream`, with `Cache-Control: no-cache` and
  `X-Accel-Buffering: no`. Each frame is `event: <name>` plus one `data:` line of JSON, so a
  newline inside a token never splits a frame.
- Events, always in this order: `sources` -> `token`* -> `citations` -> `done`. `error`
  replaces the rest if the provider fails mid-answer, and the stream ends there.
  - `sources`: `[{number, chunk_id, document_id, chunk_index, heading_path, text}]`. `number`
    is the N in `[N]` and in `<document id='N'>`.
  - `token`: `{text}`, raw model output, for live display only.
  - `citations`: `{citations: [{number, chunk_id, document_id}], dropped: [n...]}`. The ids
    are resolved on the server from `number`, never taken from model text.
  - `done`: `{answer, refused, external_links, skipped_chunks}`. `answer` is the
    authoritative text, with invalid citations removed and any echoed prompt wrappers
    (`<document ...>`, `</document>`, `<question>`, ...) stripped (seen in M5 5.5). A client should replace the streamed
    text with it.
  - `error`: `{code, message}` with a fixed message per error class (`llm_unavailable`,
    `llm_rate_limited`, `llm_refused`, `llm_rejected`, `llm_not_configured`). Provider details
    stay in the server log.
- Retrieval runs before the stream opens, so its failures are ordinary HTTP 503/500. An LLM
  that isn't configured is a 503 before streaming starts.
- Nothing usable retrieved: `sources` is empty, the refusal text is sent as one `token`,
  `done.refused` is true, and the LLM is never called.
- A client disconnect stops the generator, which closes the provider's HTTP stream.

## Limits (from the M5 security review)
- At most `CHAT_MAX_CONCURRENT_ANSWERS` (default 4) LLM answers run at once per process. When
  all are taken, the stream is a single `error` event `llm_busy` and no LLM call is made. A
  refusal needs no slot.
- `LLM_ANSWER_DEADLINE_SECONDS` (default 180) bounds a whole answer, not each read. Past it,
  the stream ends with `llm_timeout` and the provider stream is closed.
- Any unexpected exception during generation ends with a generic `llm_error` event, never a
  truncated stream.
- Cost: on Anthropic every answer may use up to `ANTHROPIC_MAX_TOKENS` (16000) because
  thinking counts toward `max_tokens`, so `ANSWER_MAX_TOKENS` is a floor-raised value there.
  There is no per-tenant quota yet; that comes with the M7 per-tenant rate limiter.

## Alternatives considered
- Validating citations per token while streaming: citations can be split across tokens
  (`[1` then `]`), so a final validated `answer` is simpler and exact.
- WebSockets: bidirectional, but not needed for one answer per request. SSE works through
  plain HTTP tooling and proxies.

## Consequences
- The raw `token` stream may briefly show an invalid citation such as `[9]` before `done`
  corrects it. That's documented for clients and tested.
- `sources` carries chunk text, the caller's own tenant data, so the client can show
  quotes without a second request.
