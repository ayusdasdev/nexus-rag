---
name: test-writer
description: Use when adding or changing backend code. Writes pytest tests following this
  project's conventions (fixtures, fakes, naming, assertion style).
---
1. Unit tests in tests/unit, integration in tests/integration (mark with @pytest.mark.integration).
2. Use Fake providers (FakeEmbedder/FakeLLM) from app/providers, never real models or network.
3. File test_<module>.py; one behavior per test; name tests test_<behavior>_<condition>.
4. Every endpoint: happy path, 401 without token, 422 on bad input, cross-tenant access -> 404.
5. Assert on full response shape via the Pydantic schema, not just status code.
6. For pure functions add table-driven tests with hand-computed expected values.
