# ADR-0014: A read-only MCP server authenticated by tenant-bound API keys (M9)

Date: 2026-10-12
Status: accepted

## Context
M9 (guide 9.2) exposes Nexus to agents as an MCP server: read-only tools, a credential bound
to one tenant, and no tenant argument anywhere. The guide's credential is a login JWT in
`NEXUS_TOKEN`. That token expires after 60 minutes and carries the user's full rights; an
admin's token can delete documents. MCP configs are plain files on the user's machine, so
the credential in them should be worth as little as possible if leaked.

## Decision
- **Credential: read-only API keys (your choice).**
  - **Key and storage:** `nxk_` plus 256 random bits. Only the SHA-256 is stored (new table
    `api_keys`, migration `d340d515c9b9`); the key is shown once at creation. With 256
    random bits, a fast hash is enough.
  - **Management:** admins create, list and revoke keys at `/v1/api-keys`; members get 403. A
    composite FK ties the creator to the tenant. Revoked or unknown keys get 401.
  - **What a key is:** a non-admin reader of its tenant. It is never admin, even when an
    admin created it, so no search debug and no traces. Rate limits are charged to its tenant
    and its creator.
  - **Default deny:** `get_current_user` lets a key reach only `API_KEY_OPERATIONS`: search,
    list documents, get document, list chunks. Every other route, including routes added
    later, is 403 for a key.
  - **How it matches:** on (HTTP method, endpoint name); the name is the OpenAPI operation
    id, unique app-wide. In FastAPI 0.142 the route path seen by a dependency doesn't include
    the `/v1` prefix (probed), so paths would be fragile. A test pins the four names to their
    paths, and a rename fails closed.
- **Server: `app/mcp_server/`, on the official SDK `mcp==2.3.0`** (your approval; `MCPServer`
  over stdio).
  - **Thin adapter:** it calls the REST API with the key, so auth, tenant isolation and rate
    limits all come from the API. It never touches the database or the vector store.
  - **Tools:** `search_documents(query, top_k 1-8)` and `list_documents(limit 1-50)`, both
    annotated read-only and non-destructive. No tool schema has a tenant field (tested).
  - **Configuration:** only from the environment, `NEXUS_API_URL` and `NEXUS_API_KEY`. The
    URL must be https, or plain http to localhost; otherwise the server exits before serving.
    It never reads `.env` or the app's settings. It doesn't follow redirects and ignores
    proxy settings from the environment, as the CLI does.
  - **Output caps:** at most 8 excerpts, each cut at 800 characters, labelled
    `file#chunk_index`, with the section heading and score.
  - **Untrusted text:** each excerpt sits in a `<document ...>` block that its own text can't
    close (our delimiter is neutralised, attribute values escaped), under a note to treat it
    as data. The calling agent decides what to do with it; this marks the boundary but can't
    enforce it.
  - **Errors:** a 401, 403, 429, 422 or 5xx response becomes a readable MCP tool error. Server
    details from a 5xx are not passed on.
  - **Output channel:** stdout carries only the protocol (tested). Logs go to stderr as JSON
    lines, and the key is never logged (tested).

## Alternatives considered
- JWT in `NEXUS_TOKEN` (the guide): simplest, but it expires hourly and holds full user
  rights if leaked.
- Reusing the CLI's saved token file: no secret in the MCP config, but the same expiry and
  rights.
- A hand-written JSON-RPC server with no new dependency: our own protocol implementation to
  keep compatible with clients.
- Allowlisting by route path: fragile in this FastAPI version (see above).

## Consequences
- **Risk if leaked:** a key in an MCP config can read one tenant's documents until revoked.
  It can't write, delete, chat (an LLM cost), read conversations or traces, or mint keys.
- **Long-lived:** keys don't expire; revocation is the control. Expiry dates can come later
  if needed.
- **New read routes** need an explicit entry in `API_KEY_OPERATIONS` before a key can use
  them.
- **Prompt injection** through returned text: we mark boundaries and say "data, not
  instructions". The calling agent is still responsible for not obeying document text
  (ADR-0007's stance, on the producer side).
- **Verified on 2026-10-12** against the local API and the eval tenant (details in
  `docs/mcp.md`):
  - both tools work (search took 52.0 s cold on CPU);
  - no tenant field exists in any schema;
  - delete, upload and key-minting with a key are 403, and the document stays;
  - the key appears in no output or log;
  - a revoked key gets 401.
- **Unverified here:** the MCP Inspector (`npx`, a download) and registering the server in
  Claude Code (it edits your Claude config). The commands are documented in `docs/mcp.md`;
  run them yourself.
