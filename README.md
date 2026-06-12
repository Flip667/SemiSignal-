# SemiSignal

**Semiconductor analyst agent** — Microsoft Agents League @ AI Skills Fest, *Reasoning Agents* track.

SemiSignal ingests public SEC EDGAR filings for a watchlist of semiconductor companies and reasons in multiple steps to produce a **sourced comparative note** focused on **geopolitical risk** (export controls, China, Taiwan, supply chain). Every claim is traced back to a specific filing.

> Research tool. Not **investment advice**.

## Problem solved

Analysts manually read hundreds of pages of 10-K / 10-Q / 20-F filings to track how export-control exposure evolves across the sector. SemiSignal automates collection, extraction of risk sections (Item 1A, Item 7), and produces a **cross-company comparative analysis** in seconds — with full citations.

## Architecture

See `architecture.mermaid`. Microsoft Foundry at the center, model **Claude Opus 4.8**, 4 tools wired to the EDGAR API, grounding on filing content, sourced output.

Reasoning loop: **PLAN → RETRIEVE → GROUND → ANALYZE → VERIFY → SYNTHESIZE**, displayed live in the interface.

## Stack

- Microsoft Foundry — Claude Opus 4.8 deployed (Global Standard)
- Anthropic Python SDK (Foundry endpoint, Messages API format)
- Claude native tool-calling for the 4 EDGAR tools
- Python + Streamlit (UI + live reasoning display)
- SEC EDGAR API (public, free) + local SQLite cache

## Getting started

```bash
pip install -r requirements.txt

# 1. Set your real name + email in semisignal/config.py (USER_AGENT)
# 2. Copy .env.example to .env and add your Foundry credentials
cp .env.example .env   # then edit

# Validate EDGAR access (no Foundry required):
python -m semisignal.edgar_client

# Launch the app:
streamlit run app.py
```

## Agent tools

| Tool | Role |
|---|---|
| `list_filings` | Recent filings for a ticker, filtered by type |
| `fetch_filing_section` | Text of a section (Item 1A / Item 7) from the Nth filing |
| `scan_geopolitical_exposure` | Count + passages for geopolitical keywords |
| `get_financial_metric` | Latest XBRL value for a financial concept |

## Demo

[![SemiSignal Demo](https://img.youtube.com/vi/LJn7Q2zGSgU/0.jpg)](https://youtu.be/LJn7Q2zGSgU)
