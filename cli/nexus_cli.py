"""nexus: a terminal client for the Nexus RAG API (M7 7.4). Standard library + httpx only.

    nexus login --email you@example.com          # password from a prompt (or --password-stdin)
    nexus upload notes.pdf --wait                # wait until it's searchable
    nexus docs | nexus search "retention" [--debug]
    nexus ask "How long are readings kept?" [--conversation ID]
    nexus history [--conversation ID] | nexus logout

The token is stored in ~/.nexus/config.json (mode 0600, directory 0700), bound to the API
URL it was issued for. It is never printed, never sent to another server, never sent over
plain http except to loopback, and never follows a redirect.
"""

import argparse
import getpass
import ipaddress
import json
import os
import stat
import sys
import tempfile
import time
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_CONFIG = Path("~/.nexus/config.json")


class CliError(Exception):
    """A message for the user; main() prints it and exits 1."""


# --- pure helpers ---------------------------------------------------------------------


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Server-Sent Events -> (event name, JSON data). Handles CRLF, comments and multi-line
    data, and flushes a final event even without a trailing blank line."""
    event, data = "message", list[str]()
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].lstrip())
    if data:
        yield event, json.loads("\n".join(data))


def check_transport_is_safe(api_url: str) -> None:
    """A bearer token goes only over https, or plain http to this machine."""
    parts = urlsplit(api_url)
    if parts.scheme == "https":
        return
    if parts.scheme == "http":
        host = parts.hostname or ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if loopback:
            return
    raise CliError(
        f"refusing to send the token to {api_url}: use https (or a loopback host)"
    )


def _private_parent(parent: Path) -> None:
    """Create the directory 0700, or check an existing one is safe to hold a token in.
    An existing directory is never chmodded (it may be $HOME, or /tmp)."""
    if not parent.exists():
        parent.mkdir(parents=True, mode=0o700)
        os.chmod(parent, 0o700)
        return
    info = parent.stat()
    if info.st_mode & 0o022:
        raise CliError(
            f"{parent} is writable by other users; keep the config somewhere private"
        )
    if info.st_uid != os.getuid():
        raise CliError(
            f"{parent} belongs to another user; keep the config somewhere private"
        )


def save_config(path: Path, config: dict[str, Any]) -> None:
    """Write atomically, mode 0600: a unique temp file (O_EXCL, so a planted symlink can't
    redirect it), fully written and fsynced, then renamed over the config."""
    try:
        _private_parent(path.parent)
        fd, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".nexus-", suffix=".tmp"
        )
        try:
            data = memoryview(json.dumps(config).encode("utf-8"))
            while data:
                data = data[os.write(fd, data) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.replace(temporary, path)
        except OSError:
            os.unlink(temporary)
            raise
    except OSError as exc:
        raise CliError(
            f"can't write {path}: {exc.strerror or type(exc).__name__}"
        ) from exc


def load_config(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise CliError(f"{path} is readable by other users; run `chmod 600 {path}`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(
            f"{path} is not a readable nexus config; run `nexus login`"
        ) from exc
    if not isinstance(data, dict):
        raise CliError(f"{path} is not a nexus config")
    return data


# Control characters (except newline and tab), DEL and C1: what terminal escape sequences
# are made of. Everything shown to the user passes through here (M7 review, MEDIUM-4).
_CONTROL: dict[int, None] = {
    c: None for c in [*range(9), *range(11, 32), *range(0x7F, 0xA0)]
}


def sanitize(text: str) -> str:
    return text.translate(_CONTROL)


def _conversation_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise CliError("--conversation must be a conversation id (a UUID)") from exc


def _problem_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    message = f"error {response.status_code}: {detail or response.reason_phrase}"
    if isinstance(body, dict) and body.get("request_id"):
        message += f" (request_id {body['request_id']})"
    if response.status_code == 429 and response.headers.get("retry-after"):
        message += f"; retry in {response.headers['retry-after']} s"
    return message


# --- the API session ------------------------------------------------------------------


class Session:
    def __init__(
        self,
        args: argparse.Namespace,
        transport: httpx.BaseTransport | None,
        stdout: TextIO,
        stderr: TextIO,
    ) -> None:
        self.config_path = Path(args.config).expanduser()
        self.requested_url: str | None = args.api_url
        self.transport = transport
        self.out = stdout
        self.err = stderr

    def _client(self, api_url: str, token: str | None) -> httpx.Client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.Client(
            base_url=api_url,
            headers=headers,
            transport=self.transport,
            follow_redirects=False,
            # No proxy, netrc or certificate overrides from the environment for the token.
            trust_env=False,
            timeout=httpx.Timeout(30.0, read=600.0),
        )

    def anonymous(self) -> httpx.Client:
        return self._client(self.requested_url or DEFAULT_API_URL, None)

    def authed(self) -> httpx.Client:
        config = load_config(self.config_path)
        if not config or not config.get("token") or not config.get("api_url"):
            raise CliError("not logged in: run `nexus login` first")
        issued_for = str(config["api_url"])
        if self.requested_url and self.requested_url.rstrip("/") != issued_for.rstrip(
            "/"
        ):
            raise CliError(
                f"the saved token was issued for {issued_for}; "
                f"run `nexus --api-url {self.requested_url} login` to use another server"
            )
        check_transport_is_safe(issued_for)
        return self._client(issued_for, str(config["token"]))

    def print(self, text: str = "", end: str = "\n") -> None:
        self.out.write(sanitize(text) + end)
        self.out.flush()


def _check(response: httpx.Response) -> httpx.Response:
    if response.is_redirect:
        raise CliError(
            "the API answered with a redirect; not followed (check --api-url)"
        )
    if not response.is_success:
        raise CliError(_problem_message(response))
    return response


def _pages(
    client: httpx.Client, url: str, key: str = "items"
) -> Iterator[dict[str, Any]]:
    after: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 100}
        if after:
            params["after"] = after
        body = _check(client.get(url, params=params)).json()
        yield from body[key]
        after = body.get("next_cursor")
        if not after:
            return


# --- commands -------------------------------------------------------------------------


def cmd_login(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    api_url = s.requested_url or DEFAULT_API_URL
    check_transport_is_safe(api_url)
    # Say where the password is about to go before asking for it.
    s.print(f"Logging in to {api_url} as {args.email}")
    if args.password_stdin:
        password = stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
    with s.anonymous() as client:
        response = client.post(
            "/v1/auth/login", json={"email": args.email, "password": password}
        )
    token = _check(response).json()["access_token"]
    save_config(s.config_path, {"api_url": api_url, "token": token})
    s.print(f"Logged in to {api_url}; token saved to {s.config_path} (mode 0600).")
    return 0


def cmd_logout(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    s.config_path.unlink(missing_ok=True)
    s.print("Logged out.")
    return 0


def cmd_upload(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    path = Path(args.path)
    with s.authed() as client:
        with path.open("rb") as handle:
            response = client.post("/v1/documents", files={"file": (path.name, handle)})
        document = _check(response).json()
        s.print(f"Uploaded {path.name}: {document['id']} ({document['status']})")
        if not args.wait:
            return 0
        deadline = time.monotonic() + args.timeout
        status = document["status"]
        while status not in ("ready", "failed"):
            if time.monotonic() > deadline:
                raise CliError(f"still {status} after {args.timeout} s")
            time.sleep(args.poll)
            document = _check(client.get(f"/v1/documents/{document['id']}")).json()
            status = document["status"]
            s.print(f"  ... {status}")
    if status == "failed":
        raise CliError(f"{path.name} failed: {document.get('error')}")
    s.print(f"{path.name} is ready.")
    return 0


def cmd_docs(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    with s.authed() as client:
        for document in _pages(client, "/v1/documents"):
            s.print(
                f"{document['id']}  {document['status']:<10}  {document['filename']}"
            )
    return 0


def cmd_search(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    body: dict[str, Any] = {"query": args.query}
    if args.debug:
        body["debug"] = True
    with s.authed() as client:
        result = _check(client.post("/v1/search", json=body)).json()
    for rank, hit in enumerate(result["items"], start=1):
        s.print(f"{rank}. ({hit['score']:.4f}) {hit.get('heading_path') or '-'}")
        preview = " ".join(
            hit["text"].split()
        )  # chunk newlines would break the listing
        s.print(f"   {preview[:300]}")
    if args.debug and result.get("trace"):
        stages = ", ".join(
            f"{st['name']} {st['ms']:.0f} ms" for st in result["trace"]["stages"]
        )
        s.print(f"trace: {stages}")
    return 0


def cmd_ask(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    url = (
        f"/v1/conversations/{_conversation_id(args.conversation)}/messages"
        if args.conversation
        else "/v1/chat"
    )
    sources: list[dict[str, Any]] = []
    with (
        s.authed() as client,
        client.stream("POST", url, json={"question": args.question}) as r,
    ):
        if not r.is_success:
            r.read()
            _check(r)
        for event, data in parse_sse(r.iter_lines()):
            if event == "sources":
                sources = data["sources"]
                if data.get("rewritten_query"):
                    s.print(f"Searched for: {data['rewritten_query']}")
            elif event == "token":
                s.print(data["text"], end="")
            elif event == "error":
                s.print()
                raise CliError(f"answer failed: {data['code']}: {data['message']}")
            elif event == "done":
                s.print()
                s.print(f"Answer: {data['answer']}")
                for link in data.get("external_links", []):
                    s.print(f"(link in answer, not opened: {link})")
    if sources:
        s.print("Sources:")
        for source in sources:
            s.print(f"  [{source['number']}] {source.get('heading_path') or '-'}")
    return 0


def cmd_history(s: Session, args: argparse.Namespace, stdin: TextIO) -> int:
    with s.authed() as client:
        if args.conversation:
            for message in _pages(
                client,
                f"/v1/conversations/{_conversation_id(args.conversation)}",
                "messages",
            ):
                s.print(f"{message['role']}: {message['content']}")
        else:
            for conversation in _pages(client, "/v1/conversations"):
                s.print(
                    f"{conversation['id']}  {conversation.get('title') or '(untitled)'}"
                )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus", description="Nexus RAG from the terminal."
    )
    parser.add_argument(
        "--api-url", default=os.environ.get("NEXUS_API_URL"), help="API base URL"
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("NEXUS_CONFIG", str(DEFAULT_CONFIG)),
        help="where the token is stored (default ~/.nexus/config.json)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login", help="log in and save the token")
    login.add_argument("--email", required=True)
    login.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin"
    )
    login.set_defaults(run=cmd_login)

    commands.add_parser("logout", help="forget the saved token").set_defaults(
        run=cmd_logout
    )

    upload = commands.add_parser("upload", help="upload a document")
    upload.add_argument("path")
    upload.add_argument(
        "--wait", action="store_true", help="wait until ready or failed"
    )
    upload.add_argument("--poll", type=float, default=2.0, help=argparse.SUPPRESS)
    upload.add_argument("--timeout", type=float, default=600.0, help="seconds to wait")
    upload.set_defaults(run=cmd_upload)

    commands.add_parser("docs", help="list your documents").set_defaults(run=cmd_docs)

    search = commands.add_parser("search", help="search your documents")
    search.add_argument("query")
    search.add_argument("--debug", action="store_true", help="show the trace (admins)")
    search.set_defaults(run=cmd_search)

    ask = commands.add_parser("ask", help="ask a question; streams the answer")
    ask.add_argument("question")
    ask.add_argument("--conversation", help="add the question to this conversation")
    ask.set_defaults(run=cmd_ask)

    history = commands.add_parser("history", help="your conversations, or one of them")
    history.add_argument("--conversation")
    history.set_defaults(run=cmd_history)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = _parser().parse_args(argv)
    session = Session(args, transport, stdout, stderr)
    try:
        code: int = args.run(session, args, stdin)
        return code
    except CliError as exc:
        stderr.write(f"nexus: {sanitize(str(exc))}\n")
        return 1
    except (KeyError, TypeError, ValueError) as exc:
        stderr.write(
            f"nexus: unexpected response from the API ({type(exc).__name__})\n"
        )
        return 1
    except httpx.HTTPError as exc:
        # The exception type only: messages can include URLs, never the token, but stay terse.
        stderr.write(f"nexus: could not reach the API ({type(exc).__name__})\n")
        return 1


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
