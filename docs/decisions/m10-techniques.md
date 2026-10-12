# M10: advanced techniques, built, measured and not built

Date: 2026-10-12. The guide's M10 lesson is to form a hypothesis, implement it, measure it,
and keep only what earns its cost. Measurements are in `eval-log.md` (M10-1, M10-2); dev
only, since the v1 hold-out is spent.

## Built behind settings and measured on dev (both kept off)

| technique | setting | dev result | decision |
|---|---|---|---|
| Weighted RRF (dense 1.5 / 2.0 vs BM25 1.0) | `RRF_DENSE_WEIGHT` (default 1.0) | E3: R@10 34 -> 35, R@5 31 -> 32, MRR 0.635 -> 0.639; only 2 questions moved. The 5 dense-only ranking failures didn't move, because with rerank on, fusion only picks the reranker's window. | **off**: below the +2-question rule fixed beforehand |
| Quote-then-cite answer prompt | `ANSWER_STYLE` (default `cite`) | Cites a gold source 15/40 -> 21/41; uncited, malformed and bare-citation answers all go to 0. But exact correct refusals fall 4/7 -> 0/7, because a Quote: line is always written, and Answer:-part facts fall 7 -> 5. | **off**: the refusal and facts conditions of the rule fail |

## Considered and not built here (with the evidence)

- **Contextual retrieval** (an LLM-written blurb per chunk). It raises *candidate* recall
  for ambiguous chunks, and the failure analysis found 0 retrieval misses: every missed gold
  chunk was already a dense top-40 candidate. Cost on this CPU: one llama3.2:3b call per
  chunk, roughly 3-12 h for 473 chunks.
- **Multi-query / HyDE.** These aim at paraphrase recall, but dense already *finds* those
  gold chunks; ranking and context use are where they fail. Each adds one or more LLM calls
  (about 30-90 s each here) on top of a ~38 s rerank, and multi-query multiplies retrieval
  work.
- **Agentic RAG.** Multi-hop and comparison questions are where it helps, and our
  multi-chunk set is small (7 on dev). Small local models are unreliable at tool calling (the
  guide's own warning), and 4 steps at 1-2 min each on CPU puts one answer at many minutes.
  Revisit with a stronger model behind the existing provider Protocol.
- **Self-querying filters.** Our questions rarely name a document or a date; there is nothing
  to filter on.
- **Semantic caching** (design only). Key the cache by (tenant_id, query embedding), never by
  the embedding alone (cross-tenant leakage is the classic bug). Invalidate a tenant's
  entries on any ingest or delete. Use a strict similarity threshold, since false hits answer
  a different question. Build it only once traces show repeated queries; they don't yet
  (`query_traces` would show it).

## M10.6: techniques to know without building

- **GraphRAG** (entities and relations in a graph, community summaries). For "global"
  questions across a corpus (themes, trends) and multi-hop relations between entities. Not
  here: our questions are local, about one or two documents, and its indexing cost is
  heavy.
- **ColBERT / late interaction** (one vector per token). When single-vector dense isn't
  precise enough and storage is affordable. Here the cross-encoder reranker already does
  token-level matching, at query time.
- **Fine-tuning embeddings** (contrastive pairs with hard negatives). For specialised
  vocabulary where general models underperform. It would need a labelled set larger than
  v1's 60 questions, and the eval set must never be the training set.
- **Multimodal RAG** (index images, tables and slides via vision models or captions). For
  documents whose figures or tables carry the answer. Our tables are text (pymupdf4llm
  extracts them as Markdown), which is enough for this corpus.
- **Long context vs RAG.** Stuffing a small corpus into one prompt works when it fits.
  Retrieval still wins on cost, latency, freshness, per-tenant access control and citing,
  and here a 4096-token local context makes it a non-option.
- **Document-level ACLs** (permissions per document, in the payload filter beyond the
  tenant). For enterprise sharing rules. It would be another `vector_store` filter
  condition next to `tenant_id`, plus ownership on document reads.
- **Incremental indexing and versioning.** For living document sets: re-embed only what
  changed and keep versions. We already have deterministic chunk ids and `delete_stale`
  (ADR-0002), which is the base for it.
- **PII redaction** (detect and mask at ingestion). For regulated data. It would sit in the
  worker between parsing and chunking, before anything is embedded or logged.
