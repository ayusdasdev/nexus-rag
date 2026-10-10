# nexus CLI: a real end-to-end run (M7 7.4)

Date: 2026-10-09, at `b455019`. Local stack, Celery worker (stopped before the LLM calls),
uvicorn with `LLM_PROVIDER=ollama`, `llama3.2:3b` on CPU (cold). A fresh tenant was created
with curl, because the CLI has no signup command. `NEXUS_CONFIG` pointed at a scratch file,
which was removed afterwards. Output as printed, except that the email is elided in the first
command line.

```text
$ nexus --api-url http://localhost:8000 login --email ... --password-stdin
Logged in to http://localhost:8000; token saved to .../nexus_cli_config.json (mode 0600).
[exit 0, 0.62 s]
600 nexus_cli_config.json
700 (dir)

$ nexus upload sample_docs/01_text_heavy.pdf --wait
Uploaded 01_text_heavy.pdf: 658957fa-fbcc-4220-9ad3-5d895b9dcebd (uploaded)
  ... processing
  ... embedding
  ... embedding
  ... embedding
  ... embedding
  ... embedding
  ... ready
01_text_heavy.pdf is ready.
[exit 0, 14.63 s]

$ nexus upload sample_docs/06_scanned.pdf --wait
Uploaded 06_scanned.pdf: 9086e649-f262-4d35-b22f-c9b99827a3ec (uploaded)
  ... failed
nexus: 06_scanned.pdf failed: No extractable text: the file is scanned, image-only, or nearly empty.
[exit 1, 2.40 s]

$ nexus docs
9086e649-f262-4d35-b22f-c9b99827a3ec  failed      06_scanned.pdf
658957fa-fbcc-4220-9ad3-5d895b9dcebd  ready       01_text_heavy.pdf
[exit 0, 0.32 s]

$ nexus search "how long are readings kept"        (lines cut at 160 characters)
1. (5.5880) Nexus Widgets Deployment Guide > 8. Data retention
   Readings are kept for ninety days at full resolution and for two years as hourly averages. Alert events are kept for one year. Administrators can export any 
2. (-0.7956) Nexus Widgets Deployment Guide > 11. Frequently asked questions
   ...
6. (-4.6875) Nexus Widgets Deployment Guide > 10. Glossary
   Widget. A battery-powered sensor that measures temperature and humidity and, on some models, vibration. Each widget has a serial number printed on its label 

Hub. The gateway that j

$ nexus ask "How long are readings kept at full resolution?"
Readings are kept for ninety days at full resolution.
Answer: Readings are kept for ninety days at full resolution.
Sources:
  [1] Nexus Widgets Deployment Guide > 8. Data retention
  [2] Nexus Widgets Deployment Guide > 5. Alerts > 5.2 Choosing durations
  [3] Nexus Widgets Deployment Guide > 5. Alerts > 5.1 Writing rules
  [4] Nexus Widgets Deployment Guide > 4. Calibration
  [5] Nexus Widgets Deployment Guide > 6. Network and security
  [6] Nexus Widgets Deployment Guide > 11. Frequently asked questions
[exit 0, 162.86 s]

$ nexus history
[exit 0, 1.35 s]

$ nexus --api-url https://evil.example docs
nexus: the saved token was issued for http://localhost:8000; run `nexus --api-url https://evil.example login` to use another server
[exit 1, 0.28 s]
```

Notes:
- The answer is correct but **uncited** this time: the 3B model left out `[1]`. That's M8
  data on citation-format adherence, as in M5 5.5 Q3.
- `ask` took 162.86 s with a cold model on CPU; the guide's "demo in under two minutes"
  isn't reachable on this machine with Ollama.
- The search timing wasn't captured (the command was piped through `head`, which cut its
  timing line).
- Search previews keep newlines from the chunk text (hit 6). This is cosmetic, and fixed after
  this run.
