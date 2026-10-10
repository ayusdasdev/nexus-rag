"""Ingest the frozen M8 corpus into the eval tenant through the real API (guide 8.1).

    uv run python -m eval.tools.ingest_corpus --email eval@nexus.local [--signup]

Password: --password, or $EVAL_PASSWORD, or a prompt. Writes eval/state/eval_tenant.json
(tenant id, document ids and final statuses; local to this database, so not committed).
Exits 1 if any document didn't become ready.
"""

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "corpus"
DEFAULT_STATE = ROOT / "eval" / "state" / "eval_tenant.json"


def main(
    argv: list[str] | None = None, transport: httpx.BaseTransport | None = None
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=os.environ.get("EVAL_PASSWORD"))
    parser.add_argument(
        "--signup", action="store_true", help="create the eval tenant first"
    )
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--poll", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args(argv)
    password = args.password or getpass.getpass("Eval tenant password: ")

    manifest = json.loads((CORPUS / "manifest.json").read_text())
    with httpx.Client(
        base_url=args.api_url, transport=transport, timeout=120.0, trust_env=False
    ) as client:
        if args.signup:
            signup = client.post(
                "/v1/auth/signup",
                json={
                    "tenant_name": "M8 eval",
                    "email": args.email,
                    "password": password,
                },
            )
            if signup.status_code not in (201, 409):
                signup.raise_for_status()
        login = client.post(
            "/v1/auth/login", json={"email": args.email, "password": password}
        )
        login.raise_for_status()
        body = login.json()
        client.headers["Authorization"] = f"Bearer {body['access_token']}"

        documents = []
        for entry in manifest["files"]:
            path = CORPUS / entry["file"]
            with path.open("rb") as handle:
                response = client.post(
                    "/v1/documents", files={"file": (path.name, handle)}
                )
            response.raise_for_status()
            documents.append({"file": entry["file"], "id": response.json()["id"]})
            print(f"uploaded {entry['file']}", flush=True)

        deadline = time.monotonic() + args.timeout
        pending = {d["id"]: d for d in documents}
        while pending and time.monotonic() < deadline:
            time.sleep(args.poll)
            for doc_id in list(pending):
                status = client.get(f"/v1/documents/{doc_id}").json()
                if status["status"] in ("ready", "failed"):
                    pending.pop(doc_id).update(
                        status=status["status"], error=status["error"]
                    )
                    print(f"{status['status']:6s} {doc_id}", flush=True)
        for doc in pending.values():
            doc.update(status="timeout", error=None)

    state = Path(args.state)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "api_url": args.api_url,
                "email": args.email,
                "tenant_id": body["user"]["tenant_id"],
                "user_id": body["user"]["id"],
                "corpus_commit": manifest["frozen_at_commit"],
                "documents": documents,
            },
            indent=2,
        )
        + "\n"
    )
    not_ready = [d for d in documents if d["status"] != "ready"]
    for doc in not_ready:
        print(
            f"NOT READY: {doc['file']} ({doc['status']}: {doc['error']})",
            file=sys.stderr,
        )
    return 1 if not_ready else 0


if __name__ == "__main__":
    sys.exit(main())
