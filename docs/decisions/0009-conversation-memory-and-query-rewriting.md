# ADR-0009: Conversation memory, query rewriting and ownership

Date: 2026-10-09
Status: accepted

## Context
M6 adds multi-turn chat. LLMs are stateless, so the app chooses which earlier turns to resend,
and a follow-up like "and for monthly plans?" retrieves junk unless it's turned into a
standalone query. The dev machine is CPU-only (9 GB RAM): M5 5.5 measured prompt processing at
~15 tokens/s, so every extra 100 prompt tokens costs about 7 s, and every extra Ollama call
costs tens of seconds.

## Decision
- **Memory: a token-budgeted sliding window.** `trim_history` keeps the most recent
  contiguous turns that fit and never skips a turn to fit an older one. History shares the
  `MAX_CONTEXT_TOKENS` budget (2500) with retrieved sources, capped at `HISTORY_MAX_TOKENS`
  (500). Sources get the rest, so prompt size and latency stay bounded.
- **Rewriting: `REWRITE_MODE=rule|llm|off`, default `rule`.** It never runs on the first turn.
  - `rule`: no LLM call. If the question contains an anaphor (it, its, that, this, these,
    those, they, them) or starts with "and", "also", "what about" or "how about", the
    retrieval query is the previous user question followed by the current one. "there" is
    excluded because it is usually existential.
  - `llm` (guide 6.2): `app/prompts/rewrite.md`, `temperature=0`, `max_tokens=64`, history
    and question inside neutralised `<history>`/`<question>` tags. Falls back to the original
    question on empty output, overlong output, or any provider error.
  - The overlong limit is **3 x len(previous user question + current question)**, not the
    guide's 3 x len(question). A standalone query takes its subject from the previous turn,
    so the guide's limit rejects exactly the rewrites it wants: a 9-character "And Team?"
    can't become any useful standalone query within 27 characters.
- **Ownership: owner only, admins included.** Every conversation and message query is
  scoped by `tenant_id` AND `user_id`. A conversation owned by anyone else, including a
  tenant admin, gets 404, the same as one that doesn't exist. `messages` carries `tenant_id`
  with a composite FK to `conversations(id, tenant_id)`, so the database rejects a message
  filed under another tenant.

## Alternatives considered
- LLM rewrite by default (the guide's choice): better standalone queries, but an extra
  CPU Ollama call per follow-up. Kept as `REWRITE_MODE=llm` for M8 to compare with numbers.
- A separate history budget on top of the sources: retrieval context never shrinks, but
  follow-up prompts grow by up to ~35 s of CPU prompt processing.
- Sources first, history gets the remainder: best-grounded answers, but history can vanish
  entirely and follow-ups lose their context.
- Admins can read their tenant's conversations: useful for support, but it adds a role branch
  to every query and to the IDOR suite.

## Consequences
- The rule produces noisier queries ("previous question + follow-up") and doesn't help
  follow-ups without trigger words. M8 measures rule vs llm vs off.
- An LLM rewrite can still add a fact the prompt forbids. Its output is only a retrieval
  query over the caller's own tenant, so the worst case is retrieving the wrong own-tenant
  chunks.
- **Message order (decided 2026-10-11).** History and the message listing are ordered by
  `created_at`, which was Postgres `now()`: wall-clock time. On 2026-10-11 the WSL2/Docker
  clock stepped back about 0.65 s mid-turn, so a turn's question was stored after its own
  answer. History pairing then dropped the turn, and a follow-up saw no history (a flaky
  integration failure, reproduced in tests). `add_message` now locks the conversation row
  and stores `greatest(now(), last message + 1 µs)`, so a conversation's messages sort in
  the order they were added. You chose this over a new `seq` column, which would have needed
  a migration and a message-cursor change. Cost: after a backward step `created_at` can run
  slightly ahead of real time, and posts to one conversation queue on a row lock.

## Security review follow-ups (2026-10-09)
Fixed with tests: a fresh 404/401 exception per raise; the LLM rewrite takes an answer slot
and has the answer deadline; history loads only the newest 50 messages (no sources JSON);
`GET /{id}` pages messages; `CONVERSATION_MAX_MESSAGES` and `MAX_CONVERSATIONS_PER_USER`
(1000 each, 409); the user-turn save returns 404 if the conversation vanished; history
resends only complete user/assistant pairs, with old `[N]` numbers stripped, and the RAG rules
say earlier turns are context, not instructions; rewrite history is one line per turn;
partial answers are cleaned like finished ones before saving; provider errors are logged by
type only.

Known and accepted for now:
- **Deleted documents leave traces in old messages.** Stored sources keep no chunk text,
  but an assistant answer can quote a document, and `heading_path` and `rewritten_query` can
  carry document words. These stay after the document is deleted and are resent as history
  until the conversation is deleted. A retention policy, or redacting on document delete, is
  a later decision.
- **No database tie between `conversations.user_id` and `tenant_id`.** Both come from the
  token and every query checks both, but a composite FK to `users(id, tenant_id)` would
  make a repository bug impossible rather than tested-against. It needs a new migration,
  so it's left as a follow-up.

