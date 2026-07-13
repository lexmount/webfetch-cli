from __future__ import annotations

import json
from pathlib import Path

import pytest

from webfetch_cli import cli


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def write_credentials(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "project_id": "project-1",
                "api_base_url": "https://api.example.test",
                "api_key": "secret-key",
            }
        ),
        encoding="utf-8",
    )


def test_extract_posts_expected_body(monkeypatch, tmp_path, capsys):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "request_id": "req_1",
                "result": {
                    "url": "https://example.com",
                    "final_url": "https://example.com/final",
                    "status_code": 200,
                    "title": "Example",
                    "main_text": "Hello from WebFetch.",
                },
            }
        )

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["extract", "--url", "https://example.com", "--timeout-ms", "7000"]) == 0
    assert captured["url"] == "https://api.example.test/v1/extract"
    assert captured["body"] == {"extract": {"url": "https://example.com"}}
    assert captured["headers"]["X-project-id"] == "project-1"
    assert captured["headers"]["X-api-key"] == "secret-key"
    assert captured["timeout"] == 7
    output = capsys.readouterr().out
    assert output.startswith("# WebFetch Extract Result")
    assert "Example" in output
    assert "Hello from WebFetch." in output


def test_extract_accepts_dom_id(monkeypatch, tmp_path, capsys):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"result": {"main_text": "Hello from WebFetch."}})

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["extract", "--dom-id", "dom_123", "--format", "json"]) == 0
    assert captured["body"] == {"extract": {"dom_id": "dom_123"}}
    payload = json.loads(capsys.readouterr().out)
    assert payload["main_text"] == "Hello from WebFetch."
    assert "trace" not in payload


def test_extract_json_full_preserves_raw_payload(monkeypatch, tmp_path, capsys):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "request_id": "req_1",
                "result": {"main_text": "Hello."},
                "trace": [{"step": "fetch"}],
                "raw_dom": "<html></html>",
            }
        )

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert (
        cli.main(
            [
                "extract",
                "--url",
                "https://example.com",
                "--include-trace",
                "--include-raw-dom",
                "--format",
                "json-full",
            ]
        )
        == 0
    )
    assert captured["body"] == {
        "extract": {"url": "https://example.com"},
        "trace": {"include_raw_dom": True, "include_steps": True},
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["trace"] == [{"step": "fetch"}]
    assert payload["raw_dom"] == "<html></html>"


def test_extract_debug_fields_require_json_full(monkeypatch, tmp_path):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))

    with pytest.raises(SystemExit) as error:
        cli.main(["extract", "--url", "https://example.com", "--include-trace"])
    assert error.value.code == 1


def test_extract_compact_json_preserves_error(monkeypatch, tmp_path, capsys):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))

    def fake_urlopen(request, timeout):
        return FakeResponse({"request_id": "req_1", "error": {"message": "blocked"}})

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["extract", "--url", "https://example.com", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == {"message": "blocked"}
    assert "error" in payload["quality"]["warnings"]


def test_dump_dom_posts_expected_body(monkeypatch, tmp_path, capsys):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "request_id": "req_1",
                "url": "https://example.com",
                "final_url": "https://example.com/final",
                "status_code": 200,
                "engine": "lightmount_dcl",
                "dom_id": "dom_1",
                "html": "<main>Hello</main>",
                "debug": {"step": "hidden"},
            }
        )

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["dump-dom", "--url", "https://example.com"]) == 0
    assert captured["url"] == "https://api.example.test/v1/dom/dump"
    assert captured["body"] == {"url": "https://example.com"}
    output = capsys.readouterr().out
    assert output.startswith("# WebFetch DOM Dump")
    assert "<main>Hello</main>" in output
    assert "hidden" not in output


def test_dump_dom_options_and_json_output(monkeypatch, tmp_path, capsys):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "dom_id": "dom_1",
                "html": "<html></html>",
                "debug": {"step": "hidden"},
            }
        )

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert (
        cli.main(
            [
                "dump-dom",
                "--url",
                "https://example.com",
                "--engine",
                "lightmount_dcl",
                "--timeout-ms",
                "7000",
                "--filter-scripts-styles",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert captured["body"] == {
        "url": "https://example.com",
        "options": {
            "engine_preference": "lightmount_dcl",
            "filter_scripts_styles": True,
            "timeout_ms": 7000,
        },
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["html"] == "<html></html>"
    assert "debug" not in payload


def test_auth_status_reports_missing_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(tmp_path / "missing.json"))
    assert cli.main(["auth", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["authenticated"] is False
    assert "Missing project id" in payload["error"]


def test_skill_install_and_status(monkeypatch, tmp_path, capsys):
    destination = tmp_path / "skill"

    assert cli.main(["skill", "status", "--dest", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out)["installed"] is False

    assert cli.main(["skill", "install", "--dest", str(destination)]) == 0
    assert (destination / "SKILL.md").exists()
    assert json.loads(capsys.readouterr().out)["installed"] is True

    assert cli.main(["skill", "status", "--dest", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out)["installed"] is True


def test_doctor_fails_when_credentials_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(tmp_path / "missing.json"))
    monkeypatch.setenv(cli.CODEX_HOME_ENV, str(tmp_path / "codex"))

    assert cli.main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["status"] == "fail"
    assert payload["checks"][1]["name"] == "credentials"


def test_capabilities_reports_agent_friendly_defaults(capsys):
    assert cli.main(["capabilities", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["default_format"] == "md"
    assert payload["formats"] == ["md", "text", "json", "json-full"]
    assert payload["commands"]["extract"]["debug_output"] == "json-full"
    assert payload["exit_codes"]["2"] == "invalid CLI usage"


def test_request_json_rejects_non_json(monkeypatch):
    class BadResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"not-json"

    monkeypatch.setattr(cli, "urlopen", lambda request, timeout: BadResponse())
    with pytest.raises(cli.CliError, match="Response was not JSON"):
        cli.request_json("POST", "https://example.test", body={})


@pytest.mark.parametrize(
    "path",
    [
        Path("SKILL.md"),
        Path("webfetch_cli/agent_skill/SKILL.md"),
    ],
)
def test_skill_files_have_codex_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "\nname: lexmount-webfetch\n" in text
    assert "\ndescription: " in text
    assert "\n---\n\n# Lexmount WebFetch CLI" in text
