import json

import pytest

from fulfilliq.cli import main


def test_cli_ingest_verify_stats(raw_dir, tmp_path, capsys):
    db = tmp_path / "db.sqlite3"
    assert (
        main(
            [
                "ingest",
                "--raw-dir",
                str(raw_dir),
                "--db-path",
                str(db),
                "--report-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "success"
    assert main(["verify", "--db-path", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["integrity_check"] == "ok"
    assert main(["stats", "--db-path", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["overview"]["total_orders"] == 6


def test_cli_missing_database_exits_with_actionable_error(tmp_path, capsys):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(SystemExit) as exc:
        main(["verify", "--db-path", str(missing)])
    assert exc.value.code == 1
    assert "Error:" in capsys.readouterr().err
    assert not missing.exists()
