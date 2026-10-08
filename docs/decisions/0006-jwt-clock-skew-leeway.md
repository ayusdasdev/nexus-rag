# ADR-0006: JWT validation tolerates 5 s of clock skew

Date: 2026-10-08
Status: accepted

## Context
Integration tests failed now and then with `401 Could not validate credentials` on a request
made right after signup. Measured on the dev machine, the WSL wall clock steps back about
1.4 s (-0.59 s, then -0.82 s) every ~30 s, and `dmesg` logs `Time jumped backwards`. PyJWT
stores `iat` in whole seconds and rejects `iat > now` with zero leeway by default. A token
issued just before a step therefore failed for about a second.
`tests/unit/test_security.py::test_a_token_issued_2s_in_the_future_is_accepted` reproduced
it before the fix: `ImmatureSignatureError: The token is not yet valid (iat)`. Clocks also
drift between hosts in a real deployment, so this isn't only a WSL problem.

## Decision
- New setting `JWT_LEEWAY_SECONDS`, default 5, range 0-60, passed as `leeway` to
  `jwt.decode` in `app/core/security.py`.
- PyJWT applies the same leeway to `iat`, `nbf` and `exp`. A token is therefore accepted
  up to 5 s before its `iat` and up to 5 s after its `exp`, and never beyond that.

## Alternatives considered
- Dropping `iat` validation (`verify_iat: False`): this fixes the symptom, but `exp` still has
  no tolerance, and a token far in the future would pass unnoticed.
- Fixing only the WSL clock: it doesn't protect production, and the steps come from the host.

## Consequences
- An expired token stays usable for at most 5 s more. That's acceptable against a 60-minute
  lifetime, and `le=60` stops the setting from growing into a real extension.
- Tests: a 2 s future `iat` is accepted, a 30 s future `iat` is rejected, a token expired by
  10 s is rejected, and the setting defaults to 5 and rejects -1 and 61.
