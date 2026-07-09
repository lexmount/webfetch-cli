"""Command-line entrypoint for Lexmount WebFetch."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any, NoReturn
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from webfetch_cli import __version__

DEFAULT_API_BASE_URL = "https://api.lexmount.cn"
DEFAULT_CONSOLE_URL = "https://browser.lexmount.cn"
CONNECT_BASE_URL_ENV = "LEXMOUNT_WEBFETCH_CONNECT_BASE_URL"
BASE_URL_ENV = "LEXMOUNT_WEBFETCH_BASE_URL"
API_KEY_ENV = "LEXMOUNT_API_KEY"
PROJECT_ID_ENV = "LEXMOUNT_PROJECT_ID"
CREDENTIALS_FILE_ENV = "LEXMOUNT_WEBFETCH_CREDENTIALS_FILE"
DEFAULT_CONNECT_SCOPES = ("browser:read",)
DEFAULT_CALLBACK_TIMEOUT_SECONDS = 300
DEFAULT_HTTP_TIMEOUT_SECONDS = 30
CODEX_HOME_ENV = "CODEX_HOME"
DEFAULT_CODEX_SKILL_DIRECTORY_NAME = "lexmount-webfetch"


class CliError(Exception):
    """User-facing CLI error."""


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def fail(message: str, *, code: int = 1) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def normalize_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    except Exception:
        return value.rstrip("/")


def credentials_file() -> Path:
    override = os.environ.get(CREDENTIALS_FILE_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "lexmount" / "webfetch-cli" / "credentials.json"


def read_credentials() -> dict[str, Any] | None:
    path = credentials_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CliError(f"Unable to read credentials file {path}: {error}") from error


def write_credentials(payload: dict[str, Any]) -> None:
    path = credentials_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def clear_credentials() -> bool:
    path = credentials_file()
    if not path.exists():
        return False
    path.unlink()
    return True


def active_credentials() -> dict[str, str]:
    stored = read_credentials() or {}
    project_id = os.environ.get(PROJECT_ID_ENV) or str(stored.get("project_id") or "")
    api_key = os.environ.get(API_KEY_ENV) or str(stored.get("api_key") or "")
    base_url = (
        os.environ.get(BASE_URL_ENV)
        or str(stored.get("api_base_url") or "")
        or DEFAULT_API_BASE_URL
    )
    if not project_id:
        raise CliError(
            f"Missing project id. Run webfetch-cli auth login or set {PROJECT_ID_ENV}."
        )
    if not api_key:
        raise CliError(f"Missing API key. Run webfetch-cli auth login or set {API_KEY_ENV}.")
    return {
        "project_id": project_id,
        "api_key": api_key,
        "api_base_url": normalize_base_url(base_url),
    }


def request_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    data = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {"raw": text}
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("details")
            or f"HTTP {error.code}"
        )
        raise CliError(f"{message}") from error
    except URLError as error:
        raise CliError(f"Network request failed: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise CliError(f"Response was not JSON: {error}") from error


def webfetch_request(path: str, body: dict[str, Any], timeout_ms: int | None) -> dict[str, Any]:
    credentials = active_credentials()
    timeout_seconds = (
        max(timeout_ms / 1000, 1) if timeout_ms is not None else DEFAULT_HTTP_TIMEOUT_SECONDS
    )
    return request_json(
        "POST",
        f"{credentials['api_base_url']}{path}",
        body=body,
        headers={
            "x-project-id": credentials["project_id"],
            "x-api-key": credentials["api_key"],
        },
        timeout=timeout_seconds,
    )


def base64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def random_urlsafe(length: int = 64) -> str:
    return secrets.token_urlsafe(length)[:length]


def make_callback_server(expected_state: str):
    result: dict[str, str] = {}
    event = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = dict(parse_qsl(urlsplit(self.path).query, keep_blank_values=True))
            if query.get("state") != expected_state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid state.")
                return
            if query.get("error"):
                result["error"] = query.get("error", "authorization_error")
            elif query.get("code"):
                result["code"] = query["code"]
            else:
                result["error"] = "missing_code"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Lexmount WebFetch login received. You can close this tab.")
            event.set()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return server, event, result


def connect_authorize_url(
    connect_base_url: str,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: tuple[str, ...],
) -> str:
    base = normalize_base_url(connect_base_url)
    query = urlencode(
        {
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(scopes),
            "client_name": "webfetch-cli",
        }
    )
    return f"{base}/connect/codex?{query}"


def exchange_code(
    connect_base_url: str,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{normalize_base_url(connect_base_url)}/api/connect/codex/exchange",
        body={
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )


def command_auth_login(args: argparse.Namespace) -> int:
    connect_base_url = normalize_base_url(
        args.connect_base_url
        or os.environ.get(CONNECT_BASE_URL_ENV)
        or DEFAULT_CONSOLE_URL
    )
    state = random_urlsafe(32)
    code_verifier = random_urlsafe(64)
    code_challenge = base64url_sha256(code_verifier)
    server, event, result = make_callback_server(state)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    login_url = connect_authorize_url(
        connect_base_url,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        scopes=DEFAULT_CONNECT_SCOPES,
    )

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if args.open:
            webbrowser.open(login_url)
        emit_json(
            {
                "ok": True,
                "login_url": login_url,
                "opened_browser": bool(args.open),
                "callback_timeout_seconds": args.timeout_seconds,
            }
        )
        if not event.wait(args.timeout_seconds):
            raise CliError("Timed out waiting for browser authorization callback.")
        if result.get("error"):
            raise CliError(f"Authorization failed: {result['error']}")
        exchanged = exchange_code(
            connect_base_url,
            code=result["code"],
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        credential = exchanged.get("credential") or exchanged
        payload = {
            "project_id": credential.get("project_id") or exchanged.get("project_id"),
            "api_base_url": normalize_base_url(
                credential.get("api_base_url")
                or exchanged.get("api_base_url")
                or DEFAULT_API_BASE_URL
            ),
            "api_key": credential.get("api_key") or exchanged.get("api_key"),
            "scope": exchanged.get("scope") or list(DEFAULT_CONNECT_SCOPES),
            "saved_at": int(time.time()),
        }
        if not payload["project_id"] or not payload["api_key"]:
            raise CliError("Connect exchange did not return project_id and api_key.")
        write_credentials(payload)
        emit_json(
            {
                "ok": True,
                "credentials_saved": True,
                "credentials_file": str(credentials_file()),
                "project_id": payload["project_id"],
                "api_base_url": payload["api_base_url"],
                "scope": payload["scope"],
            }
        )
    finally:
        server.shutdown()
        server.server_close()
    return 0


def command_auth_status(_args: argparse.Namespace) -> int:
    stored = read_credentials()
    payload = {
        "authenticated": False,
        "credentials_file": str(credentials_file()),
        "sources": {
            "project_id": "env" if os.environ.get(PROJECT_ID_ENV) else None,
            "api_key": "env" if os.environ.get(API_KEY_ENV) else None,
            "api_base_url": "env" if os.environ.get(BASE_URL_ENV) else None,
        },
    }
    if stored:
        payload["stored"] = {
            "project_id": stored.get("project_id"),
            "api_base_url": stored.get("api_base_url"),
            "scope": stored.get("scope"),
            "has_api_key": bool(stored.get("api_key")),
        }
        payload["sources"] = {
            key: value or "credentials_file" for key, value in payload["sources"].items()
        }
    try:
        credentials = active_credentials()
        payload.update(
            {
                "authenticated": True,
                "project_id": credentials["project_id"],
                "api_base_url": credentials["api_base_url"],
                "has_api_key": True,
            }
        )
    except CliError as error:
        payload["error"] = str(error)
    emit_json(payload)
    return 0


def command_auth_clear(_args: argparse.Namespace) -> int:
    removed = clear_credentials()
    emit_json({"ok": True, "removed": removed, "credentials_file": str(credentials_file())})
    return 0


def command_extract(args: argparse.Namespace) -> int:
    if not args.url and not args.dom_id:
        raise CliError("Either --url or --dom-id is required.")
    body = {
        "extract": {
            **({"url": args.url} if args.url else {}),
            **({"dom_id": args.dom_id} if args.dom_id else {}),
        }
    }
    emit_json(webfetch_request("/v1/extract", body, args.timeout_ms))
    return 0


def command_dump_dom(args: argparse.Namespace) -> int:
    emit_json(webfetch_request("/v1/dom/dump", {"url": args.url}, args.timeout_ms))
    return 0


def default_codex_home() -> Path:
    value = os.environ.get(CODEX_HOME_ENV)
    return Path(value).expanduser() if value else Path.home() / ".codex"


def skill_destination(args: argparse.Namespace) -> Path:
    if args.dest:
        return Path(args.dest).expanduser()
    return default_codex_home() / "skills" / DEFAULT_CODEX_SKILL_DIRECTORY_NAME


def skill_source() -> Path:
    return Path(str(importlib_resources.files("webfetch_cli").joinpath("agent_skill")))


def command_skill_status(args: argparse.Namespace) -> int:
    dest = skill_destination(args)
    source = skill_source()
    skill_file = dest / "SKILL.md"
    emit_json(
        {
            "installed": skill_file.exists(),
            "destination": str(dest),
            "source": str(source),
            "skill_file": str(skill_file),
        }
    )
    return 0


def command_skill_install(args: argparse.Namespace) -> int:
    dest = skill_destination(args)
    source = skill_source()
    if dest.exists():
        if not args.force:
            raise CliError(f"Skill destination already exists: {dest}. Use --force.")
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)
    emit_json({"ok": True, "installed": True, "destination": str(dest)})
    return 0


def command_doctor(_args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []
    checks.append({"name": "cli_version", "status": "pass", "version": __version__})
    try:
        credentials = active_credentials()
        checks.append(
            {
                "name": "credentials",
                "status": "pass",
                "project_id": credentials["project_id"],
                "api_base_url": credentials["api_base_url"],
                "has_api_key": True,
            }
        )
    except CliError as error:
        checks.append({"name": "credentials", "status": "fail", "message": str(error)})
    dest = default_codex_home() / "skills" / DEFAULT_CODEX_SKILL_DIRECTORY_NAME
    checks.append(
        {
            "name": "codex_skill",
            "status": "pass" if (dest / "SKILL.md").exists() else "warn",
            "destination": str(dest),
            "repair_command": "webfetch-cli skill install --force",
        }
    )
    status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    emit_json({"ok": status == "pass", "status": status, "checks": checks})
    return 0 if status == "pass" else 1


def command_version(_args: argparse.Namespace) -> int:
    emit_json(
        {
            "name": "webfetch-cli",
            "version": __version__,
            "api_base_url_env": BASE_URL_ENV,
            "credentials_file": str(credentials_file()),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webfetch-cli")
    parser.add_argument("--version", action="version", version=f"webfetch-cli {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    version_parser = subparsers.add_parser("version")
    version_parser.set_defaults(func=command_version)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--json", action="store_true", help="Output is always JSON.")
    doctor_parser.set_defaults(func=command_doctor)

    auth_parser = subparsers.add_parser("auth")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_login = auth_subparsers.add_parser("login")
    auth_login.add_argument("--open", action="store_true", help="Open login URL.")
    auth_login.add_argument("--connect-base-url", help="Lexmount console base URL.")
    auth_login.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_CALLBACK_TIMEOUT_SECONDS,
    )
    auth_login.set_defaults(func=command_auth_login)
    auth_status = auth_subparsers.add_parser("status")
    auth_status.set_defaults(func=command_auth_status)
    auth_clear = auth_subparsers.add_parser("clear-credentials")
    auth_clear.set_defaults(func=command_auth_clear)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--url")
    extract.add_argument("--dom-id")
    extract.add_argument("--timeout-ms", type=int)
    extract.set_defaults(func=command_extract)

    dump_dom = subparsers.add_parser("dump-dom")
    dump_dom.add_argument("--url", required=True)
    dump_dom.add_argument("--timeout-ms", type=int)
    dump_dom.set_defaults(func=command_dump_dom)

    skill = subparsers.add_parser("skill")
    skill_subparsers = skill.add_subparsers(dest="skill_command", required=True)
    skill_status = skill_subparsers.add_parser("status")
    skill_status.add_argument("--dest")
    skill_status.set_defaults(func=command_skill_status)
    skill_install = skill_subparsers.add_parser("install")
    skill_install.add_argument("--dest")
    skill_install.add_argument("--force", action="store_true")
    skill_install.set_defaults(func=command_skill_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except CliError as error:
        fail(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
