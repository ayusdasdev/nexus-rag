# Dependency log

Every new dependency must be explained in chat *before* it's added, then logged here in the
same commit that adds it (see CLAUDE.md "Do NOT").

| Date       | Dependency     | Why                                                                                          | Commit |
|------------|----------------|-----------------------------------------------------------------------------------------------|--------|
| 2026-09-30 | import-linter  | Enforces the "DB/Qdrant calls only in repositories/" and "provider SDKs only in providers/" architecture rules automatically (`.importlinter`), instead of relying on code review to catch violations. | - |
| 2026-10-02 | PyJWT          | JWT encode/decode for the auth token scheme (claims sub/tid/role/exp, HS256). Chosen over python-jose: smaller surface, ships py.typed (mypy --strict compatible), FastAPI-ecosystem default. | - |
| 2026-10-02 | bcrypt         | Password hashing. Chosen over passlib (unmaintained, no real type stubs) and argon2-cffi (needs libffi/cffi at build time); bcrypt ships prebuilt wheels and py.typed. | - |
