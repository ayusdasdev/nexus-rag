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
