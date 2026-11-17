import json

import pytest

from app.cli import main
from app.config import Settings


@pytest.fixture
def cli_config(monkeypatch, tracker, sessions):
    monkeypatch.setattr(
        "app.cli.Settings", lambda: Settings(database_url=str(sessions.kw["bind"].url))
    )
    monkeypatch.setattr("app.cli.KeitaroClient", lambda *_: tracker.client)


def test_catalogs_command(cli_config, capsys):
    assert main(["catalogs"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["domains"][0]["id"] == 1


def test_create_command_and_status(cli_config, capsys):
    args = [
        "create",
        "--name",
        "cli",
        "--countries",
        "AU,MX",
        "--offer-id",
        "10",
        "--domain-id",
        "1",
        "--group-id",
        "2",
        "--source-id",
        "3",
        "--key",
        "cli-create-key-1",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["phase"] == "complete"
    assert main(["status", "--key", "cli-create-key-1"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["campaign_id"] == result["campaign_id"]


def test_invalid_cli_request_never_writes(cli_config, tracker, capsys):
    assert (
        main(
            [
                "create",
                "--name",
                "bad",
                "--countries",
                "XX",
                "--offer-id",
                "10",
                "--domain-id",
                "1",
                "--group-id",
                "2",
                "--source-id",
                "3",
                "--key",
                "cli-bad-key-1",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"]
    assert tracker.calls == []
