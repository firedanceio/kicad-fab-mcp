from pathlib import Path

import pytest

from kicad_fab.bom import read_pos
from kicad_fab_mcp import server

F = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_board(tmp_path, monkeypatch):
    """A stand-in board: kicad-cli calls return the fixture placements and DRC report."""
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)")
    monkeypatch.setattr(server.kicad, "positions", lambda b, out: Path(out).write_text((F / "pos.csv").read_text()) and Path(out))
    monkeypatch.setattr(server.kicad, "drc", lambda b, out: __import__("json").loads((F / "drc.json").read_text()))
    monkeypatch.setattr(server.kicad, "gerbers_zip", lambda b, out, work: Path(out).write_bytes(b"zip") and Path(out))
    return board


def test_drc_summary_from_report():
    r = server.drc_summary(str(F / "drc.json"))
    assert r["errors"] == 2 and r["ready"] is False


def test_bom_check_offline(fake_board):
    r = server.bom_check(str(fake_board), str(F / "bom.csv"), check_stock=False)
    assert r["board_problems"] == [] and r["ready"] is True


def test_review_board_blocks_on_drc_and_lists_rotation_checks(fake_board):
    r = server.review_board(str(fake_board), str(F / "bom.csv"), check_stock=False)
    assert r["ready_to_order"] is False
    assert r["blockers"] == ["2 DRC error(s)"]
    assert "SOT-23" in r["check_rotation_in_viewer"]


def test_review_board_with_fixes_has_nothing_to_check(fake_board):
    r = server.review_board(str(fake_board), str(F / "bom.csv"), check_stock=False, fixes=str(F / "fixes.csv"))
    assert r["check_rotation_in_viewer"] == []


def test_write_order_files_refuses_to_overwrite(fake_board, tmp_path):
    out = tmp_path / "order"
    first = server.write_order_files(str(fake_board), str(F / "bom.csv"), str(out))
    assert len(first["written"]) == 3 and all(Path(p).exists() for p in first["written"])
    with pytest.raises(ValueError, match="already exist"):
        server.write_order_files(str(fake_board), str(F / "bom.csv"), str(out))
    server.write_order_files(str(fake_board), str(F / "bom.csv"), str(out), overwrite=True)


def test_missing_files_are_reported():
    with pytest.raises(ValueError, match="not found"):
        server.drc_summary("/nope/board.kicad_pcb")
