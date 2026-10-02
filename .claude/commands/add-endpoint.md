---
description: Scaffold a new API endpoint following project conventions
argument-hint: <METHOD> <path> <purpose>
---
Add this endpoint: $ARGUMENTS
Follow CLAUDE.md. Create/extend: Pydantic request+response schemas (with examples), the
router function with docstring and `summary`, the service function, repository access if
needed, and tests (happy path, auth failure, validation error). tenant_id must come from
Depends(get_tenant_id). Run make lint && make test and show the results.
