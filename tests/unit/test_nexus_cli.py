"""The nexus CLI (M7 7.4): SSE parsing, token storage and every command, against httpx's
MockTransport (no server, no network)."""

import io
import json
import os
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import nexus_cli as cli

API = "http://localhost:8000"
TOKEN = "header.payload.signature-SECRET-TOKEN"


# --- SSE parsing --------------------------------------------------------------------


def test_parse_sse_reads_events_in_order() -> None:
    lines = [
        "event: sources",
        'data: {"sources": []}',
        "",
        "event: token",
        'data: {"text": "Two "}',
        "",
        "event: done",
        'data: {"answer": "Two."}',
        "",
    ]

    assert list(cli.parse_sse(lines)) == [
        ("sources", {"sources": []}),
        ("token", {"text": "Two "}),
        ("done", {"answer": "Two."}),
    ]


def test_parse_sse_joins_multi_line_data_ignores_comments_and_handles_crlf() -> None:
    lines = [
        ": keep-alive",
        "event: token\r",
        'data: {"text":\r',
        'data: "a\\nb"}\r',
        "\r",
    ]

    assert list(cli.parse_sse(lines)) == [("token", {"text": "a\nb"})]


def test_parse_sse_flushes_a_last_event_without_a_trailing_blank_line() -> None:
    assert list(cli.parse_sse(["event: done", 'data: {"answer": "x"}'])) == [
        ("done", {"answer": "x"})
    ]


def test_parse_sse_defaults_the_event_name_to_message() -> None:
    assert list(cli.parse_sse(['data: {"a": 1}', ""])) == [("message", {"a": 1})]


# --- token storage ------------------------------------------------------------------


def test_the_config_is_written_0600_in_a_0700_directory(tmp_path: Path) -> None:
    path = tmp_path / "nexus" / "config.json"

    cli.save_config(path, {"api_url": API, "token": TOKEN})

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert cli.load_config(path) == {"api_url": API, "token": TOKEN}


def test_overwriting_a_loose_config_tightens_it(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}")
    os.chmod(path, 0o644)

    cli.save_config(path, {"api_url": API, "token": TOKEN})

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_config_readable_by_others_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    cli.save_config(path, {"api_url": API, "token": TOKEN})
    os.chmod(path, 0o644)

    with pytest.raises(cli.CliError, match="readable by other users"):
        cli.load_config(path)


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://api.example.com", True),
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8000", True),
        ("http://[::1]:8000", True),
        ("http://api.example.com", False),
        ("ftp://api.example.com", False),
    ],
)
def test_a_token_is_only_ever_sent_over_https_or_to_loopback(
    url: str, allowed: bool
) -> None:
    if allowed:
        cli.check_transport_is_safe(url)
    else:
        with pytest.raises(cli.CliError):
            cli.check_transport_is_safe(url)


# --- commands, against a mock server -------------------------------------------------


class Server:
    """Records requests; answers from a route table of (method, path) -> handler."""

    def __init__(
        self, routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]]
    ):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes[(request.method, request.url.path)](request)


def _run(
    tmp_path: Path, server: Server, *argv: str, stdin: str = "", logged_in: bool = True
) -> tuple[int, str, str]:
    config = tmp_path / "config.json"
    if logged_in:
        cli.save_config(config, {"api_url": API, "token": TOKEN})
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["--config", str(config), *argv],
        transport=httpx.MockTransport(server),
        stdin=io.StringIO(stdin),
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


def _json(body: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


def test_login_stores_the_token_0600_and_never_prints_it(tmp_path: Path) -> None:
    server = Server(
        {("POST", "/v1/auth/login"): _json({"access_token": TOKEN, "user": {}})}
    )

    code, out, err = _run(
        tmp_path,
        server,
        "--api-url",
        API,
        "login",
        "--email",
        "me@example.com",
        "--password-stdin",
        stdin="correct-horse-battery\n",
        logged_in=False,
    )

    assert code == 0
    sent = json.loads(server.requests[0].content)
    assert sent == {"email": "me@example.com", "password": "correct-horse-battery"}
    saved = cli.load_config(tmp_path / "config.json")
    assert saved == {"api_url": API, "token": TOKEN}
    assert TOKEN not in out + err
    assert "correct-horse-battery" not in out + err


def test_login_failure_is_reported_without_the_password(tmp_path: Path) -> None:
    problem = {
        "status": 401,
        "title": "Unauthorized",
        "detail": "Incorrect email or password",
        "request_id": "rid-1",
        "type": "about:blank",
    }
    server = Server({("POST", "/v1/auth/login"): _json(problem, status=401)})

    code, out, err = _run(
        tmp_path,
        server,
        "--api-url",
        API,
        "login",
        "--email",
        "me@example.com",
        "--password-stdin",
        stdin="wrong-password\n",
        logged_in=False,
    )

    assert code == 1
    assert "Incorrect email or password" in err and "rid-1" in err
    assert "wrong-password" not in out + err


def test_commands_send_the_token_only_to_the_server_it_was_issued_for(
    tmp_path: Path,
) -> None:
    server = Server(
        {("GET", "/v1/documents"): _json({"items": [], "next_cursor": None})}
    )

    code, _, err = _run(tmp_path, server, "--api-url", "https://evil.example", "docs")

    assert code == 1
    assert "issued for" in err
    assert server.requests == []


def test_logout_removes_the_token(tmp_path: Path) -> None:
    code, _, _ = _run(tmp_path, Server({}), "logout")

    assert code == 0
    assert not (tmp_path / "config.json").exists()


def test_docs_follows_cursors_through_every_page(tmp_path: Path) -> None:
    pages = {
        None: {
            "items": [{"id": "d1", "filename": "a.md", "status": "ready"}],
            "next_cursor": "c1",
        },
        "c1": {
            "items": [{"id": "d2", "filename": "b.pdf", "status": "failed"}],
            "next_cursor": None,
        },
    }
    server = Server(
        {
            ("GET", "/v1/documents"): lambda r: httpx.Response(
                200, json=pages[r.url.params.get("after")]
            )
        }
    )

    code, out, _ = _run(tmp_path, server, "docs")

    assert code == 0
    assert "a.md" in out and "b.pdf" in out and "failed" in out
    assert server.requests[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_upload_wait_polls_until_ready(tmp_path: Path) -> None:
    document = tmp_path / "notes.md"
    document.write_text("# Notes")
    doc_id = str(uuid.uuid4())
    statuses = iter(["processing", "embedding", "ready"])
    server = Server(
        {
            ("POST", "/v1/documents"): _json({"id": doc_id, "status": "uploaded"}, 202),
            ("GET", f"/v1/documents/{doc_id}"): lambda r: httpx.Response(
                200, json={"id": doc_id, "status": next(statuses), "error": None}
            ),
        }
    )

    code, out, _ = _run(
        tmp_path, server, "upload", str(document), "--wait", "--poll", "0"
    )

    assert code == 0
    assert "ready" in out
    assert [r.method for r in server.requests] == ["POST", "GET", "GET", "GET"]


def test_upload_wait_reports_a_failed_document(tmp_path: Path) -> None:
    document = tmp_path / "scan.pdf"
    document.write_bytes(b"%PDF-1.4")
    doc_id = str(uuid.uuid4())
    server = Server(
        {
            ("POST", "/v1/documents"): _json({"id": doc_id, "status": "uploaded"}, 202),
            ("GET", f"/v1/documents/{doc_id}"): _json(
                {"id": doc_id, "status": "failed", "error": "No extractable text"}
            ),
        }
    )

    code, _, err = _run(
        tmp_path, server, "upload", str(document), "--wait", "--poll", "0"
    )

    assert code == 1
    assert "No extractable text" in err


def _sse(
    *events: tuple[str, dict[str, Any]],
) -> Callable[[httpx.Request], httpx.Response]:
    body = "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    )
    return lambda request: httpx.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream"}
    )


SOURCES = {
    "sources": [
        {
            "number": 1,
            "heading_path": "Guide > Data retention",
            "chunk_id": "c",
            "text": "x",
        }
    ]
}


def test_ask_streams_tokens_then_prints_the_cleaned_answer_and_sources(
    tmp_path: Path,
) -> None:
    server = Server(
        {
            ("POST", "/v1/chat"): _sse(
                ("sources", SOURCES),
                ("token", {"text": "Ninety days "}),
                ("token", {"text": "[1][9]."}),
                ("citations", {"citations": [{"number": 1}], "dropped": [9]}),
                (
                    "done",
                    {
                        "answer": "Ninety days [1].",
                        "refused": False,
                        "external_links": [],
                    },
                ),
            )
        }
    )

    code, out, _ = _run(tmp_path, server, "ask", "How long are readings kept?")

    assert code == 0
    assert "Ninety days [1][9]." in out  # streamed as it arrived
    assert "Answer: Ninety days [1]." in out  # the server's cleaned answer
    assert "[1] Guide > Data retention" in out
    assert json.loads(server.requests[0].content) == {
        "question": "How long are readings kept?"
    }


def test_ask_in_a_conversation_posts_there_and_shows_the_rewritten_query(
    tmp_path: Path,
) -> None:
    conversation = str(uuid.uuid4())
    server = Server(
        {
            ("POST", f"/v1/conversations/{conversation}/messages"): _sse(
                ("sources", {**SOURCES, "rewritten_query": "Q1 And Q2?"}),
                ("done", {"answer": "ok [1].", "refused": False, "external_links": []}),
            )
        }
    )

    code, out, _ = _run(
        tmp_path, server, "ask", "And Q2?", "--conversation", conversation
    )

    assert code == 0
    assert "Searched for: Q1 And Q2?" in out


def test_ask_reports_an_error_event(tmp_path: Path) -> None:
    server = Server(
        {
            ("POST", "/v1/chat"): _sse(
                ("sources", SOURCES), ("error", {"code": "llm_busy", "message": "busy"})
            )
        }
    )

    code, _, err = _run(tmp_path, server, "ask", "q")

    assert code == 1
    assert "llm_busy" in err


def test_ask_shows_retry_after_on_429(tmp_path: Path) -> None:
    problem = {
        "status": 429,
        "title": "Too Many Requests",
        "detail": "Rate limit exceeded",
        "request_id": "rid-2",
        "type": "about:blank",
    }
    server = Server(
        {
            ("POST", "/v1/chat"): lambda r: httpx.Response(
                429, json=problem, headers={"Retry-After": "60"}
            )
        }
    )

    code, _, err = _run(tmp_path, server, "ask", "q")

    assert code == 1
    assert "Rate limit exceeded" in err and "retry in 60 s" in err


def test_search_prints_ranked_hits(tmp_path: Path) -> None:
    server = Server(
        {
            ("POST", "/v1/search"): _json(
                {
                    "items": [
                        {"score": 0.9, "heading_path": "Guide", "text": "Ninety days."}
                    ],
                    "trace": None,
                }
            )
        }
    )

    code, out, _ = _run(tmp_path, server, "search", "retention", "--debug")

    assert code == 0
    assert "Ninety days." in out
    assert json.loads(server.requests[0].content) == {
        "query": "retention",
        "debug": True,
    }


def test_history_lists_conversations_or_one_conversations_messages(
    tmp_path: Path,
) -> None:
    conversation = str(uuid.uuid4())
    server = Server(
        {
            ("GET", "/v1/conversations"): _json(
                {
                    "items": [{"id": conversation, "title": "Charging"}],
                    "next_cursor": None,
                }
            ),
            ("GET", f"/v1/conversations/{conversation}"): _json(
                {
                    "id": conversation,
                    "title": "Charging",
                    "next_cursor": None,
                    "messages": [
                        {"role": "user", "content": "How long?"},
                        {"role": "assistant", "content": "Two hours [1]."},
                    ],
                }
            ),
        }
    )

    _, listing, _ = _run(tmp_path, server, "history")
    _, thread, _ = _run(tmp_path, server, "history", "--conversation", conversation)

    assert conversation in listing and "Charging" in listing
    assert "user: How long?" in thread and "assistant: Two hours [1]." in thread


def test_a_command_without_login_says_to_log_in(tmp_path: Path) -> None:
    code, _, err = _run(tmp_path, Server({}), "docs", logged_in=False)

    assert code == 1
    assert "nexus login" in err
