# The Nexus MCP server

`app/mcp_server/` exposes your Nexus documents to an agent (Claude Code, the MCP Inspector,
any MCP client) as two read-only tools over stdio. Design: ADR-0014.

| tool | arguments | returns |
|---|---|---|
| `search_documents` | `query` (1-1000 chars), `top_k` (1-8, default 5) | the best excerpts, each in a `<document label="file#chunk" file=… section=… score=…>` block, text cut at 800 characters |
| `list_documents` | `limit` (1-50, default 20) | file name, status and id, newest first |

There is no tenant argument: the key decides the tenant, on the server.

## 1. Create a read-only API key (admin)

Log in as an admin of the tenant, then create a key. It is shown once, so keep it:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "..."}' | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -s -X POST http://localhost:8000/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Claude Code (MCP)"}'
```

What a key can and can't do:
- It can search, list documents, read a document, and list a document's chunks, and nothing
  else (other routes are 403).
- Revoke it with `DELETE /v1/api-keys/{id}`; its next request is 401.

## 2. Run the server

```bash
NEXUS_API_URL=http://localhost:8000 NEXUS_API_KEY=nxk_... uv run python -m app.mcp_server
```

- `NEXUS_API_URL` must be https, or plain http to localhost.
- The server speaks MCP on stdin/stdout and logs JSON lines to stderr.
- It needs the API running (`make up`, `make dev`, and `make worker` for ingestion).

## 3. Inspect it with the MCP Inspector

```bash
npx @modelcontextprotocol/inspector \
  -e NEXUS_API_URL=http://localhost:8000 -e NEXUS_API_KEY=nxk_... \
  uv run python -m app.mcp_server
```

## 4. Use it from Claude Code

```bash
claude mcp add nexus \
  -e NEXUS_API_URL=http://localhost:8000 -e NEXUS_API_KEY=nxk_... \
  -- uv run --directory /path/to/nexus-rag python -m app.mcp_server
```

Then, in a new session: "Using the nexus tools, what do my documents say about calibration?
Cite the labels."

Excerpts are the user's document text. The server marks them as data, but an agent should
still never follow instructions found inside them.

## What has been verified

**Automated:** `tests/unit/test_mcp_server.py` (14 tests) runs the server as a subprocess
against a fake API over JSON-RPC. It covers initialize, tools/list, tools/call, the caps,
errors, stdout carrying only the protocol, and the absence of any tenant field.

**Real run, 2026-10-12**, against the local API with the M8 eval tenant (22 documents). The
raw output is in `~/nexus-rag-test-logs/2026-10-12-mcp-verify.out`.
- **Key:** an admin created a key through `POST /v1/api-keys` (201, scope `read`). The key
  appeared only in that response.
- **Setup and tools:** the server started over stdio and initialize returned `nexus`.
  `tools/list` returned exactly `search_documents` and `list_documents`, both
  `readOnlyHint: true` and `destructiveHint: false`. No key anywhere in either schema
  contains "tenant".
- **search_documents** ("How do I calibrate a widget?", top_k 3): 3 labelled excerpts in
  52.0 s, cold (model load plus CPU rerank). The first was `01_text_heavy.pdf#4`
  ("Nexus Widgets Deployment Guide > 4. Calibration"), each cut at 800 characters. The other
  two were the same guide text as quoted inside `generation-observations.md`. That's a
  property of this corpus, which quotes itself.
- **list_documents** (limit 5): 5 ready documents with names, statuses and ids.
- **Writes with the key:** `DELETE /v1/documents/{id}`, an upload, and `POST /v1/api-keys`
  were all 403 ("API keys are read-only"). The document was still there afterwards.
- **Hygiene:** every stdout line was a JSON-RPC message. The key appeared neither in the
  server's stdout or stderr, nor in the API's log, which also held no document text.
- **Revocation:** after the admin revoked the key (204), its next request got 401.

**Not run here:** the Inspector (step 3, `npx` downloads a package) and Claude Code
registration (step 4, it edits your Claude config). Run them yourself.
