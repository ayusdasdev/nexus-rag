# Dependency log

Every new dependency must be explained in chat *before* it's added, then logged here in the
same commit that adds it (see CLAUDE.md "Do NOT").

| Date       | Dependency     | Why                                                                                          | Commit |
|------------|----------------|-----------------------------------------------------------------------------------------------|--------|
| 2026-09-30 | import-linter  | Enforces the "DB/Qdrant calls only in repositories/" and "provider SDKs only in providers/" architecture rules automatically (`.importlinter`), instead of relying on code review to catch violations. | - |
