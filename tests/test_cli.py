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
        return FakeResponse({"ok": True})

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["extract", "--url", "https://example.com", "--timeout-ms", "7000"]) == 0
    assert captured["url"] == "https://api.example.test/v1/extract"
    assert captured["body"] == {"extract": {"url": "https://example.com"}}
    assert captured["headers"]["X-project-id"] == "project-1"
    assert captured["headers"]["X-api-key"] == "secret-key"
    assert captured["timeout"] == 7
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_extract_accepts_dom_id(monkeypatch, tmp_path):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"ok": True})

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["extract", "--dom-id", "dom_123"]) == 0
    assert captured["body"] == {"extract": {"dom_id": "dom_123"}}


def test_dump_dom_posts_expected_body(monkeypatch, tmp_path):
    credentials_file = tmp_path / "credentials.json"
    write_credentials(credentials_file)
    monkeypatch.setenv(cli.CREDENTIALS_FILE_ENV, str(credentials_file))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"dom_id": "dom_1"})

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    assert cli.main(["dump-dom", "--url", "https://example.com"]) == 0
    assert captured["url"] == "https://api.example.test/v1/dom/dump"
    assert captured["body"] == {"url": "https://example.com"}


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
