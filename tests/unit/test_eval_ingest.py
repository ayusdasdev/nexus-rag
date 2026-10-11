"""eval/tools/ingest_corpus.py against a mock API: upload every manifest file, wait, record."""

import getpass
import json
from pathlib import Path

import httpx
import pytest

from eval.tools import ingest_corpus

CORPUS = Path(__file__).resolve().parents[2] / "eval" / "corpus"


def test_ingest_uploads_every_file_waits_and_records_the_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_PASSWORD", "pw-123456")
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


# --- the password never goes on the command line (M8 security review, low) -----------


def _login_only(seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["password"])
        return httpx.Response(401)

    return httpx.MockTransport(handler)


def test_a_password_on_the_command_line_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        ingest_corpus.main(["--email", "e@example.com", "--password", "pw-123456"])

    assert exit_info.value.code == 2
    assert "--password" in capsys.readouterr().err


def test_the_password_comes_from_the_environment_at_run_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setenv("EVAL_PASSWORD", "from-env")
    monkeypatch.setattr(getpass, "getpass", lambda _p: "from-prompt")

    with pytest.raises(httpx.HTTPStatusError):
        ingest_corpus.main(
            ["--email", "e@example.com", "--state", str(tmp_path / "s.json")],
            transport=_login_only(seen),
        )

    assert seen == ["from-env"]


def test_without_the_environment_variable_the_password_is_prompted_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.delenv("EVAL_PASSWORD", raising=False)
    monkeypatch.setattr(getpass, "getpass", lambda _p: "from-prompt")

    with pytest.raises(httpx.HTTPStatusError):
        ingest_corpus.main(
            ["--email", "e@example.com", "--state", str(tmp_path / "s.json")],
            transport=_login_only(seen),
        )

    assert seen == ["from-prompt"]
