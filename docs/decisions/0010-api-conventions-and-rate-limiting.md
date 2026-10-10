# ADR-0010: API conventions, rate limiting and the CLI's token handling (M7)

Date: 2026-10-10
Status: accepted

## Context
M7 turns the API into a product (docs/api-audit.md). The audit found:
- no common error shape and no request id;
- offset pagination;
- no rate limiting, which left the M5 review's LLM-cost gap open;
- undocumented error responses.

The guide adds a terminal client. The M7 security review then found unlimited signup and login,
and unbounded credential fields.

## Decision
- **Errors:** every 4xx/5xx is RFC 9457 `application/problem+json`
  `{type, title, status, detail, request_id}`.
  - 422s list `loc`, `msg` and `type` without the submitted input.
  - 500s carry no stack trace.
- **Request ids:** a client's `X-Request-ID` is echoed if it's 1-128 characters of
  `[A-Za-z0-9._-]`; otherwise a new id is generated. The id is on every log record.
- **Pagination:** opaque cursors, `base64url(json key) + "." + HMAC-SHA256`, keyed from the
  JWT secret.
  - Each cursor is bound to its scope (tenant, user, document or conversation), so a
    forged or replayed cursor is a 422.
  - Keyset order is `(created_at, id)`, or `chunk_index` for chunks. `offset` is gone.
- **Rate limits:** token buckets in Redis, using one atomic Lua script and Redis `TIME`. Keys
  come only from the verified token, so a request is charged to both its tenant and its user
  (the user gets half the tenant's limits).

  | Class | Routes | Tenant limit |
  |---|---|---|
  | chat | `/v1/chat`, conversation messages | 5, then 1/min |
  | search | `/v1/search` | 20, then 1/5 s |
  | upload | `POST /v1/documents` | 10, then 1/min |
  | default | every other authed route | 120, then 2/s |

  - Over the limit: 429 with `Retry-After` and `X-RateLimit-*`.
  - With Redis down, chat fails closed (503) and the other classes fail open.
  - Redis sockets time out after 0.5 s.
- **Signup and login** (review HIGH-1) have no token, so they're limited per client IP and,
  in addition, signup by a global budget and login per email (hashed in the key).

  | Route | Per IP | Second bucket |
  |---|---|---|
  | signup | 3, then 3/hour | global: 30, then 30/hour |
  | login | 20, then 1/10 s | per email: 5, then 1/min |

  - The client IP is the socket peer. `X-Forwarded-For` is read only from peers in
    `TRUSTED_PROXIES`.
  - Signup stays open (your choice); the global budget bounds new tenants, and so total LLM
    cost.
  - Both routes fail closed when Redis is down.
  - Credential fields are bounded: passwords are at most 72 bytes (bcrypt), and unknown fields
    are rejected.
- **Unversioned routes:** `/auth/*` is removed; only `/v1/auth/*` exists.
- **The `nexus` CLI** uses argparse and httpx, with no new dependency.
  - The token is stored in a 0600 file written through a unique temp file. Its directory is
    created 0700, and an existing directory is never chmodded and is refused if others can
    write to it.
  - The token is bound to the API URL it was issued for, sent only over https or to loopback,
    and never on a redirect.
  - It ignores proxy and netrc settings from the environment, and is never printed.
  - All server text is shown with control characters stripped.

## Alternatives considered
- In-memory buckets: simpler, but each API process would have its own budget.
- Tenant-only buckets (the guide): one user could use up their whole tenant's allowance.
- Typer for the CLI: nicer code, but about six new packages.
- Invite-only or disabled signup: closes the tenant-minting hole completely, but changes the
  product flow. The global signup budget bounds it instead.

## Consequences and open points
- **Open decision: a 422 currently spends a rate-limit token.** This was measured: two invalid
  `/v1/chat` bodies used up a user's chat burst, and a valid request then got 429. Charging
  junk requests deters abuse. Not charging them means checking the limit after validation, so
  junk becomes free. Left as is until you decide.
- **Accepted:** within a tenant, two users can drain the tenant's chat bucket for everyone in
  it, because the user share is half (your M7 choice).
- **Accepted:** the cursor key is derived from the JWT secret, so rotating that secret
  invalidates all cursors. Cursors don't expire; the scope binding is what makes replay safe.
- **Accepted:** `nexus logout` only deletes the local file; the token stays valid until it
  expires (60 min).
- **Accepted:** `/docs` and `/openapi.json` are public. They contain no secrets or internal
  paths.
