# Copyright 2026 Firedance Multimedia LLC
# SPDX-License-Identifier: Apache-2.0
"""MCP server: ask an AI assistant whether a KiCad board is ready to order.

Built on kicad-fab-tools. Every tool except `write_order_files` is read-only: it runs kicad-cli
into a temporary folder and reports back. `write_order_files` writes into the folder you name and
refuses to overwrite files unless asked.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from kicad_fab import jlc, kicad, lcsc
from kicad_fab.bom import check_bom_against_board, read_bom, read_pos
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
READ_ONLY_NET = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

server = MCPServer(
    name="kicad-fab",
    version="0.1.0",
    instructions=(
        "Checks KiCad boards before a fab and assembly order. Start with review_board for a "
        "go/no-go report. Paths are local files on this machine. Stock and prices come from "
        "JLCPCB's public parts search, which is not a documented API; treat failed lookups as unknown."
    ),
)


def _file(path: str, what: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ValueError(f"{what} not found: {p}")
    return p


def _placements(board: Path, tmp: Path):
    return read_pos(kicad.positions(board, tmp / "pos.csv"))


def _stock(bom_lines, qty: int, spare_percent: float, attrition: int) -> list[dict]:
    rows = []
    for line in bom_lines:
        if not (line.placed and line.lcsc.upper().startswith("C")):
            continue
        need = int(len(line.designators) * qty * (1 + spare_percent / 100)) + attrition
        try:
            part = lcsc.lookup(line.lcsc)
        except Exception as e:  # network or API change: unknown, not "out of stock"
            rows.append({"lcsc": line.lcsc, "mpn": line.mpn, "status": "lookup failed", "error": str(e)})
            continue
        if part is None:
            rows.append({"lcsc": line.lcsc, "mpn": line.mpn, "status": "not found"})
            continue
        rows.append({
            "lcsc": line.lcsc, "mpn": line.mpn, "lcsc_model": part.model, "stock": part.stock, "need": need,
            "library": "basic" if part.basic else "extended",
            "status": "ok" if part.stock >= need else "short",
            "model_differs": bool(line.mpn) and part.model.replace(" ", "").lower() != line.mpn.replace(" ", "").lower(),
        })
    return rows


@server.tool(annotations=READ_ONLY)
def drc_summary(board: str, max_items: int = 20) -> dict:
    """Run KiCad's design rule check on a .kicad_pcb (or read an existing DRC .json report) and
    summarise it: counts by type and severity, then each error and unconnected item."""
    path = _file(board, "board or report")
    if path.suffix == ".json":
        import json
        report = json.loads(path.read_text(encoding="utf-8"))
    else:
        with tempfile.TemporaryDirectory() as t:
            report = kicad.drc(path, Path(t) / "drc.json")
    lines, errors = kicad.summarize_drc(report, max_items)
    return {"errors": errors, "ready": errors == 0, "summary": lines}


@server.tool(annotations=READ_ONLY_NET)
def bom_check(board: str, bom: str, boards: int = 5, check_stock: bool = True,
              spare_percent: float = 20, attrition: int = 5) -> dict:
    """Compare a BOM CSV with the board (every footprint has one BOM line, placed parts exist,
    footprint names agree) and, optionally, check live LCSC stock for `boards` boards plus spares."""
    bom_lines = read_bom(_file(bom, "BOM"))
    with tempfile.TemporaryDirectory() as t:
        placements = _placements(_file(board, "board"), Path(t))
    problems = check_bom_against_board(bom_lines, placements)
    stock = _stock(bom_lines, boards, spare_percent, attrition) if check_stock else []
    short = [s for s in stock if s["status"] != "ok"]
    return {"ready": not problems and not short, "board_problems": problems, "stock": stock,
            "stock_problems": short}


@server.tool(annotations=READ_ONLY_NET)
def bom_cost(bom: str, boards: int = 5) -> dict:
    """Price the factory-placed parts in a BOM with live LCSC price tiers for the order quantity.
    Returns per-board parts cost and the number of extended (setup-fee) parts."""
    total, extended, lines, missing = 0.0, 0, [], []
    for line in read_bom(_file(bom, "BOM")):
        if not (line.placed and line.lcsc.upper().startswith("C")):
            continue
        part = lcsc.lookup(line.lcsc)
        if part is None or not part.prices:
            missing.append(line.lcsc)
            continue
        n = len(line.designators)
        unit = part.unit_price(n * boards)
        total += unit * n
        extended += not part.basic
        lines.append({"lcsc": line.lcsc, "mpn": line.mpn, "qty_per_board": n, "unit_price": unit,
                      "line_cost_per_board": round(unit * n, 4), "library": "basic" if part.basic else "extended"})
    lines.sort(key=lambda r: r["line_cost_per_board"], reverse=True)
    return {"boards": boards, "parts_per_board_usd": round(total, 2), "extended_lines": extended,
            "lines": lines, "unpriced": missing}


@server.tool(annotations=READ_ONLY_NET)
def review_board(board: str, bom: str, boards: int = 5, check_stock: bool = True, fixes: str | None = None) -> dict:
    """Go/no-go review before ordering: DRC errors, BOM vs board mismatches, stock shortfalls and
    footprints placed without a JLCPCB rotation fix. Start here."""
    board_path, bom_path = _file(board, "board"), _file(bom, "BOM")
    bom_lines = read_bom(bom_path)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        report = kicad.drc(board_path, tmp / "drc.json")
        drc_lines, drc_errors = kicad.summarize_drc(report, 10)
        placements = _placements(board_path, tmp)
        unchecked = jlc.write_jlc(bom_lines, placements, jlc.read_fixes(fixes), tmp / "bom.csv", tmp / "cpl.csv")
    problems = check_bom_against_board(bom_lines, placements)
    stock = _stock(bom_lines, boards, 20, 5) if check_stock else []
    short = [s for s in stock if s["status"] != "ok"]
    blockers = []
    if drc_errors:
        blockers.append(f"{drc_errors} DRC error(s)")
    if problems:
        blockers.append(f"{len(problems)} BOM/board mismatch(es)")
    if short:
        blockers.append(f"{len(short)} part(s) short or not found")
    return {
        "ready_to_order": not blockers,
        "blockers": blockers,
        "drc": drc_lines,
        "bom_problems": problems,
        "stock_problems": short,
        "check_rotation_in_viewer": unchecked,
        "parts_placed": sum(1 for r in placements if any(r in l.designators and l.placed for l in bom_lines)),
    }


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def write_order_files(board: str, bom: str, out_dir: str, fixes: str | None = None, overwrite: bool = False) -> dict:
    """Write the files to upload to JLCPCB into `out_dir`: a Gerber + drill zip, the JLC BOM and
    the CPL (with rotation fixes). Refuses to replace existing files unless overwrite is true."""
    board_path, bom_path = _file(board, "board"), _file(bom, "BOM")
    out = Path(out_dir).expanduser().resolve()
    name = board_path.stem
    targets = [out / f"{name}-gerbers.zip", out / f"{name}-bom.csv", out / f"{name}-cpl.csv"]
    existing = [str(p) for p in targets if p.exists()]
    if existing and not overwrite:
        raise ValueError(f"These files already exist; pass overwrite=true to replace them: {', '.join(existing)}")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        kicad.gerbers_zip(board_path, targets[0], tmp / "gerbers")
        unchecked = jlc.write_jlc(read_bom(bom_path), _placements(board_path, tmp), jlc.read_fixes(fixes), targets[1], targets[2])
    return {"written": [str(p) for p in targets], "check_rotation_in_viewer": unchecked}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
