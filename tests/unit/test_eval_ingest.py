"""eval/tools/ingest_corpus.py against a mock API: upload every manifest file, wait, record."""

import json
from pathlib import Path

import httpx

from eval.tools import ingest_corpus

CORPUS = Path(__file__).resolve().parents[2] / "eval" / "corpus"


def test_ingest_uploads_every_file_waits_and_records_the_ids(tmp_path: Path) -> None:
    uploads: list[str] = []
    polls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/login":
            return httpx.Response(
                200,
                json={"access_token": "t", "user": {"tenant_id": "ten", "id": "usr"}},
            )
        if request.method == "POST" and request.url.path == "/v1/documents":
            name = request.content.split(b'filename="')[1].split(b'"')[0].decode()
            uploads.append(name)
            return httpx.Response(202, json={"id": f"id-{name}", "status": "uploaded"})
        doc_id = request.url.path.rsplit("/", 1)[-1]
        polls[doc_id] = polls.get(doc_id, 0) + 1
        status = "ready" if polls[doc_id] > 1 else "embedding"
        if doc_id == "id-guide.pdf" and polls[doc_id] > 1:
            status = "failed"
        return httpx.Response(
            200, json={"id": doc_id, "status": status, "error": "boom"}
        )

    state = tmp_path / "eval_tenant.json"
    code = ingest_corpus.main(
        [
            "--email",
            "eval@example.com",
            "--password",
            "pw-123456",
            "--state",
            str(state),
            "--poll",
            "0",
        ],
        transport=httpx.MockTransport(handler),
    )

    manifest = json.loads((CORPUS / "manifest.json").read_text())
    names = [f["file"] for f in manifest["files"]]
    saved = json.loads(state.read_text())
    assert sorted(uploads) == sorted(names)
    assert saved["tenant_id"] == "ten"
    assert {d["file"]: d["status"] for d in saved["documents"]}["guide.pdf"] == "failed"
    assert code == 1  # a failed document is reported, not hidden
