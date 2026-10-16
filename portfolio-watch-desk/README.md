# Portfolio Watch Desk

A personal trading dashboard published as a claude.ai Artifact:
https://claude.ai/artifact/BZcdLeKQysqsBiCeYTbTau

- **Portfolio tracking**: holdings, P&L, sector allocation, target/stop alerts and concentration flags. Holdings are stored privately per viewer (`data/users/<id>/portfolio`).
- **Market tape and regime read**: global indices, yields, oil, gold, bitcoin, the dollar, and macro context.
- **Global news wire**: stories tagged by likely impact, filterable to the ones that touch your holdings.
- **Idea board**: research-based buy/hedge/avoid candidates with thesis, risks and a rethink trigger.
- **Catalyst calendar** and an **Ask the analyst** panel that sends your holdings plus the desk data to Claude.

## Files

| File | What it is |
| --- | --- |
| `watch-desk.html` | The page source, as published to the Artifact. Declares the `db` (with `market` writable by editors only), `user` and `sample` capabilities. |
| `build_market_data.py` | Generates the market data documents from research notes. |
| `data/*.json` | The market data written to the Artifact's `market` collection (`snapshot`, `quotes`, `news`, `ideas`, `calendar`). Snapshot as of the Oct 15, 2026 close. |

To refresh the market data, update `build_market_data.py`, run it, and write each `data/*.json` file to the `market/<name>` document in the Artifact's database. The open page picks up the change live.

Prices are end-of-session snapshots, not a streaming feed. Nothing here is financial advice.
