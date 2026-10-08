# kicad-fab-mcp

Ask your AI assistant whether a KiCad board is ready to order, and get the files to upload.

> "Review `pcb/main.kicad_pcb` with `bom/parts.csv` for 10 boards."
>
> Not ready: 4 DRC errors (hole clearance on the mounting holes). BOM matches the board. Every
> part is in stock. 32 footprints have no JLCPCB rotation fix yet; check them in the placement viewer.

An MCP server built on [kicad-fab-tools](https://github.com/firedanceio/kicad-fab-tools). Other
KiCad MCP servers help you design and export; this one is the checklist before you pay for an
order.

Bring your own model: it works with any MCP client (Claude, Cursor, VS Code, or a local model in
an MCP-capable app). The server itself needs no API keys.

## Install

Needs Python 3.10+ and KiCad 8 or newer (`kicad-cli`).

Claude Code:

```sh
claude mcp add kicad-fab -- uvx --from git+https://github.com/firedanceio/kicad-fab-mcp kicad-fab-mcp
```

Any MCP client that launches stdio servers:

```json
{
  "mcpServers": {
    "kicad-fab": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/firedanceio/kicad-fab-mcp", "kicad-fab-mcp"]
    }
  }
}
```

Set `KICAD_CLI=/path/to/kicad-cli` if it isn't on your PATH or in the macOS KiCad app.

## Tools

| Tool | What it does | Changes files? |
|---|---|---|
| `review_board` | Go/no-go: DRC errors, BOM vs board, stock shortfalls, footprints with no rotation fix | No |
| `drc_summary` | Run DRC (or read a DRC JSON) and summarise it | No |
| `bom_check` | BOM vs board, plus live LCSC stock for your quantity | No |
| `bom_cost` | Per-board parts cost from live LCSC price tiers | No |
| `write_order_files` | Gerber + drill zip, JLC BOM and CPL into a folder you name | Yes, refuses to overwrite unless asked |

The BOM format and rotation-fixes file are documented in
[kicad-fab-tools](https://github.com/firedanceio/kicad-fab-tools#the-bom-file).

## Notes

- Paths are files on the machine running the server.
- Stock and prices come from the JSON endpoint behind JLCPCB's public parts search. It isn't a
  documented API; a failed lookup is reported as unknown, never as in stock.
- Nothing is ordered or uploaded. You stay in charge of the order.

## Licence

Apache-2.0. Made by [Firedance](https://firedance.io).
