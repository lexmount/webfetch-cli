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
OUTPUT_FORMATS = ("md", "text", "json", "json-full")
THIN_TEXT_THRESHOLD = 200
THIN_HTML_THRESHOLD = 500


class CliError(Exception):
    """User-facing CLI error."""


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def emit_text(value: str) -> None:
    print(value.rstrip())


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


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def text_length(value: Any) -> int:
    return len(str(value or "").strip())


def count_items(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def compact_extract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    main_text = str(result.get("main_text") or "")
    warnings = []
    if text_length(main_text) < THIN_TEXT_THRESHOLD:
        warnings.append("thin_content")
    if payload.get("error"):
        warnings.append("error")
    return {
        "request_id": payload.get("request_id"),
        "url": first_present(result, "url", "source_url"),
        "final_url": result.get("final_url"),
        "status_code": result.get("status_code"),
        "title": result.get("title"),
        "description": result.get("description"),
        "main_text": main_text,
        "publish_time": result.get("publish_time"),
        "author": result.get("author"),
        "language": result.get("language"),
        "engine": first_present(result, "engine", "engine_name"),
        "dom_id": first_present(result, "dom_id") or metadata.get("dom_id"),
        "error": payload.get("error"),
        "quality": {
            "text_length": text_length(main_text),
            "links_count": count_items(result.get("links")),
            "images_count": count_items(result.get("images")),
            "has_title": bool(result.get("title")),
            "has_description": bool(result.get("description")),
            "warnings": warnings,
        },
    }


def compact_dump_dom_payload(payload: dict[str, Any]) -> dict[str, Any]:
    html = str(payload.get("html") or "")
    warnings = []
    if text_length(html) < THIN_HTML_THRESHOLD:
        warnings.append("thin_html")
    if payload.get("error"):
        warnings.append("error")
    return {
        "request_id": payload.get("request_id"),
        "url": payload.get("url"),
        "final_url": payload.get("final_url"),
        "status_code": payload.get("status_code"),
        "fetched_at": payload.get("fetched_at"),
        "engine": payload.get("engine"),
        "dom_id": payload.get("dom_id"),
        "html": html,
        "error": payload.get("error"),
        "quality": {
            "html_length": text_length(html),
            "warnings": warnings,
        },
    }


def format_scalar(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def markdown_metadata(items: list[tuple[str, Any]]) -> str:
    return "\n".join(f"- **{label}:** {format_scalar(value)}" for label, value in items)


def markdown_warnings(warnings: list[str]) -> str:
    if not warnings:
        return "- None"
    return "\n".join(f"- {warning}" for warning in warnings)


def render_extract_markdown(payload: dict[str, Any]) -> str:
    compact = compact_extract_payload(payload)
    quality = compact["quality"]
    sections = [
        "# WebFetch Extract Result",
        markdown_metadata(
            [
                ("Request ID", compact["request_id"]),
                ("URL", compact["url"]),
                ("Final URL", compact["final_url"]),
                ("Status", compact["status_code"]),
                ("Title", compact["title"]),
                ("Author", compact["author"]),
                ("Publish Time", compact["publish_time"]),
                ("Language", compact["language"]),
                ("Engine", compact["engine"]),
                ("DOM ID", compact["dom_id"]),
            ]
        ),
        "## Extraction Quality",
        markdown_metadata(
            [
                ("Text Length", quality["text_length"]),
                ("Links", quality["links_count"]),
                ("Images", quality["images_count"]),
                ("Has Title", quality["has_title"]),
                ("Has Description", quality["has_description"]),
            ]
        ),
        "### Warnings",
        markdown_warnings(quality["warnings"]),
    ]
    if compact.get("description"):
        sections.extend(["## Description", str(compact["description"])])
    if compact.get("error"):
        sections.extend(["## Error", json.dumps(compact["error"], ensure_ascii=False)])
    sections.extend(["## Main Text", compact["main_text"] or ""])
    return "\n\n".join(sections)


def render_extract_text(payload: dict[str, Any]) -> str:
    compact = compact_extract_payload(payload)
    lines = [
        f"Title: {format_scalar(compact['title'])}",
        f"URL: {format_scalar(compact['final_url'] or compact['url'])}",
        f"Status: {format_scalar(compact['status_code'])}",
        f"Request ID: {format_scalar(compact['request_id'])}",
    ]
    if compact.get("error"):
        lines.extend(["", f"Error: {json.dumps(compact['error'], ensure_ascii=False)}"])
    lines.extend(["", compact["main_text"] or ""])
    return "\n".join(lines)


def render_dump_dom_markdown(payload: dict[str, Any]) -> str:
    compact = compact_dump_dom_payload(payload)
    quality = compact["quality"]
    sections = [
        "# WebFetch DOM Dump",
        markdown_metadata(
            [
                ("Request ID", compact["request_id"]),
                ("URL", compact["url"]),
                ("Final URL", compact["final_url"]),
                ("Status", compact["status_code"]),
                ("Fetched At", compact["fetched_at"]),
                ("Engine", compact["engine"]),
                ("DOM ID", compact["dom_id"]),
            ]
        ),
        "## Dump Quality",
        markdown_metadata([("HTML Length", quality["html_length"])]),
        "### Warnings",
        markdown_warnings(quality["warnings"]),
    ]
    if compact.get("error"):
        sections.extend(["## Error", json.dumps(compact["error"], ensure_ascii=False)])
    sections.extend(["## HTML", f"```html\n{compact['html']}\n```"])
    return "\n\n".join(sections)


def render_dump_dom_text(payload: dict[str, Any]) -> str:
    compact = compact_dump_dom_payload(payload)
    lines = [
        f"URL: {format_scalar(compact['final_url'] or compact['url'])}",
        f"Status: {format_scalar(compact['status_code'])}",
        f"Engine: {format_scalar(compact['engine'])}",
        f"DOM ID: {format_scalar(compact['dom_id'])}",
        f"Request ID: {format_scalar(compact['request_id'])}",
    ]
    if compact.get("error"):
        lines.extend(["", f"Error: {json.dumps(compact['error'], ensure_ascii=False)}"])
    lines.extend(["", compact["html"] or ""])
    return "\n".join(lines)


def emit_formatted(
    payload: dict[str, Any],
    *,
    output_format: str,
    kind: str,
) -> None:
    if output_format == "json-full":
        emit_json(payload)
        return
    if kind == "extract":
        compact = compact_extract_payload(payload)
        if output_format == "json":
            emit_json(compact)
        elif output_format == "text":
            emit_text(render_extract_text(payload))
        else:
            emit_text(render_extract_markdown(payload))
        return
    compact = compact_dump_dom_payload(payload)
    if output_format == "json":
        emit_json(compact)
    elif output_format == "text":
        emit_text(render_dump_dom_text(payload))
    else:
        emit_text(render_dump_dom_markdown(payload))


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
    client_name: str,
) -> str:
    base = normalize_base_url(connect_base_url)
    query = urlencode(
        {
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(scopes),
            "client_name": client_name,
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
        client_name=args.client_name,
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
    if (args.include_trace or args.include_raw_dom) and args.format != "json-full":
        raise CliError("--include-trace and --include-raw-dom require --format json-full.")
    body = {
        "extract": {
            **({"url": args.url} if args.url else {}),
            **({"dom_id": args.dom_id} if args.dom_id else {}),
        }
    }
    trace_options = {
        key: value
        for key, value in {
            "include_steps": args.include_trace or None,
            "include_raw_dom": args.include_raw_dom or None,
        }.items()
        if value is not None
    }
    if trace_options:
        body["trace"] = trace_options
    emit_formatted(
        webfetch_request("/v1/extract", body, args.timeout_ms),
        output_format=args.format,
        kind="extract",
    )
    return 0


def command_dump_dom(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {"url": args.url}
    options = {
        key: value
        for key, value in {
            "engine_preference": args.engine,
            "timeout_ms": args.timeout_ms,
            "filter_scripts_styles": args.filter_scripts_styles or None,
        }.items()
        if value is not None
    }
    if options:
        body["options"] = options
    emit_formatted(
        webfetch_request("/v1/dom/dump", body, args.timeout_ms),
        output_format=args.format,
        kind="dump-dom",
    )
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


def command_capabilities(_args: argparse.Namespace) -> int:
    emit_json(
        {
            "name": "webfetch-cli",
            "version": __version__,
            "default_format": "md",
            "formats": list(OUTPUT_FORMATS),
            "commands": {
                "extract": {
                    "inputs": ["url", "dom_id"],
                    "options": ["timeout_ms", "format", "include_trace", "include_raw_dom"],
                    "default_output": "agent_readable_markdown",
                    "debug_output": "json-full",
                },
                "dump-dom": {
                    "inputs": ["url"],
                    "options": [
                        "timeout_ms",
                        "format",
                        "engine",
                        "filter_scripts_styles",
                    ],
                    "default_output": "agent_readable_markdown",
                    "debug_output": "json-full",
                },
            },
            "exit_codes": {
                "0": "success",
                "1": "runtime or API error",
                "2": "invalid CLI usage",
            },
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

    capabilities_parser = subparsers.add_parser("capabilities")
    capabilities_parser.add_argument("--json", action="store_true", help="Output is JSON.")
    capabilities_parser.set_defaults(func=command_capabilities)

    auth_parser = subparsers.add_parser("auth")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_login = auth_subparsers.add_parser("login")
    auth_login.add_argument("--open", action="store_true", help="Open login URL.")
    auth_login.add_argument("--connect-base-url", help="Lexmount console base URL.")
    auth_login.add_argument(
        "--client-name",
        default="Agent",
        help="Agent name shown in the browser approval UI.",
    )
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
    extract.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="md",
        help="Output format. Default: md.",
    )
    extract.add_argument(
        "--include-trace",
        action="store_true",
        help="Request workflow trace from the API. Only visible with --format json-full.",
    )
    extract.add_argument(
        "--include-raw-dom",
        action="store_true",
        help="Request raw DOM from the API. Only visible with --format json-full.",
    )
    extract.set_defaults(func=command_extract)

    dump_dom = subparsers.add_parser("dump-dom")
    dump_dom.add_argument("--url", required=True)
    dump_dom.add_argument("--timeout-ms", type=int)
    dump_dom.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="md",
        help="Output format. Default: md.",
    )
    dump_dom.add_argument(
        "--engine",
        choices=[
            "auto",
            "http",
            "chrome",
            "chrome_cdp",
            "lightmount_lite",
            "lightmount_dcl",
            "lightmount_domstable",
        ],
        help="Preferred dump engine.",
    )
    dump_dom.add_argument(
        "--filter-scripts-styles",
        action="store_true",
        help="Ask the API to remove script and style tags from returned HTML.",
    )
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
