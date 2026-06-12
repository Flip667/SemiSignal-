# SPEC — SemiSignal: Semiconductor Analyst Agent

> Project for **Microsoft Agents League @ AI Skills Fest** — **Reasoning Agents** track (Microsoft Foundry).
> Submission deadline: **June 14 2026, 11:59 PM PT**. Scope deliberately tight to be **finished and demo-ready** in ~5 days, solo.

---

## 1. Pitch

An agent that ingests public SEC EDGAR filings for a watchlist of semiconductor companies, reasons in multiple steps (plans → retrieves → extracts → analyzes → verifies → synthesizes), and produces a **structured macro note with every claim sourced** to a specific filing.

Differentiating angle: focus on **geopolitical risk / export controls / supply chain** (China, BIS, tariffs) — an angle other participants are unlikely to pursue.

Positioning: **research / analysis tool, NOT investment advice.** The agent never says "buy" or "sell". This constraint is intentional (see §7, it's a quarter of the jury points).

---

## 2. Chosen stack

- **Microsoft Foundry Agent Service** — agent orchestration, system prompt, tool calling, traces. (REQUIRED for the track.)
- **Model**: Claude Opus 4.8 (or default reasoning model available on Foundry).
- **RAG**: integrated Foundry vector store / Azure AI Search to ground responses on retrieved filing chunks.
- **Backend**: Python + Streamlit (UI + live reasoning display).
- **Data source**: SEC EDGAR API (public, free, no key). See §4.

---

## 3. Watchlist (hard-coded in config file)

```
NVDA  - NVIDIA           CIK 0001045810
AMD   - Advanced Micro   CIK 0000002488
INTC  - Intel            CIK 0000050863
AVGO  - Broadcom         CIK 0001730168
QCOM  - Qualcomm         CIK 0000804328
MU    - Micron           CIK 0000723125
AMAT  - Applied Mat.     CIK 0000006951
LRCX  - Lam Research     CIK 0000707549
TSM   - TSMC (20-F)      CIK 0001046179
ASML  - ASML (20-F)      CIK 0000937966
```

> Verify each CIK before building via `https://www.sec.gov/files/company_tickers.json` (official ticker→CIK mapping). Do not trust the CIKs above blindly.
> Note: TSM and ASML file **20-F** (foreign issuers), not 10-K. Handle this form type.

---

## 4. EDGAR — CRITICAL access rules

**Without these → systematic 403. Must be implemented on the very first request.**

- **Required header** on EVERY request:
  `User-Agent: SemiSignal <your-name> <your-email>`
- **Rate limit: 10 requests/second max** across all EDGAR domains. Implement a rate-limiter (token bucket or simple sleep). Exceeding = temporary block, possibly a ban on repeat offenses.
- No API key, no registration. Free.

**Endpoints used:**

| Usage | URL |
|---|---|
| Ticker -> CIK | `https://www.sec.gov/files/company_tickers.json` |
| Company filings list | `https://data.sec.gov/submissions/CIK{cik10}.json` (zero-padded 10-digit CIK) |
| XBRL financial facts (1 concept) | `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/{tag}.json` |
| Full-text search | `https://efts.sec.gov/LATEST/search-index?q=...` (separate system, use only if needed) |
| Raw filing document | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/...` |

> Cache downloaded filings locally (SQLite or files) to avoid re-hitting EDGAR on every run. Saves rate limit and makes the demo reliable.

---

## 5. Agent architecture (the core — 40% of jury points)

A **single agent** with a **visible** multi-step reasoning loop (not a fragile true multi-agent — we simulate the "agentic" effect cleanly).

### Tools exposed to the agent (Foundry function calling)

```
list_filings(ticker, form_type, since_date)
    -> returns the list of recent filings (accession numbers, dates, types)

fetch_filing_section(accession_no, section)
    -> section in {"risk_factors", "mda", "business"}
    -> returns the section text (parses filing HTML, extracts Item 1A / Item 7 etc.)

scan_geopolitical_exposure(text)
    -> semantic/keyword scan: mentions of "export control", "BIS", "China", "tariff",
       "Taiwan", "national security", "entity list", "supply chain"
    -> returns relevant passages + a count per category

get_financial_metric(ticker, concept)
    -> a specific XBRL figure (e.g.: Revenues) to support/verify a claim
```

### Reasoning loop (must be visible in the trace AND the demo)

1. **PLAN** — the agent decomposes the request into subtasks and announces its plan.
2. **RETRIEVE** — calls `list_filings` then `fetch_filing_section` on the relevant filings.
3. **GROUND** — indexes chunks in the vector store; all analysis must be grounded there.
4. **ANALYZE** — calls `scan_geopolitical_exposure`, identifies risks, structures findings.
5. **VERIFY** — self-verification step: the agent re-reads its claims and checks each figure/claim against source chunks. If a claim is not supported → removed or marked "unverified".
6. **SYNTHESIZE** — final structured note, **every claim with its citation** (filing + section + date).

> Step 5 (VERIFY) is the secret weapon: it captures "Reliability & Safety" points that others will skip.

---

## 6. Output format

Structured markdown note:

```
## Risk Summary — {sector or ticker} — {date}

### Overview
{2-3 sentences, sourced}

### Geopolitical exposure / export controls
- {claim} [Source: NVDA 10-K, Item 1A, filed 2026-02-21]
- ...

### Financial signals
- {metric} [Source: XBRL Revenues, FY2025]

### Unverified claims / to investigate
- {what the agent could NOT support — transparency = safety points}

---
Research tool. Not investment advice.
```

---

## 7. Judging criteria map (keep in sight)

| Criterion | Weight | How to win it |
|---|---|---|
| Accuracy & Relevance | 20% | Real EDGAR filings, verifiable data |
| Reasoning & Multi-step | 20% | PLAN->...->SYNTHESIZE loop visible in the trace |
| Creativity & Originality | 15% | Geopolitical/export-control angle, unseen elsewhere |
| User Experience & Presentation | 15% | Clean output, clickable citations, polished demo |
| Reliability & Safety | 20% | VERIFY step, refusal to invent, no-advice disclaimer, error handling |
| Community vote (Discord) | 10% | Post early on Discord, demo that stands out |

---

## 8. 5-day plan (FINISH > AMBITIOUS)

- **Day 1 (tonight)** — Foundry setup + Azure access OK. EDGAR client with User-Agent + rate-limiter. Fetch ONE NVDA filing end-to-end and display it. *Gate: if Foundry/Azure access blocks, fix it NOW — it's the only real blocker.*
- **Day 2** — The 4 tools wired to the Foundry agent. RAG indexing. Basic reasoning loop running on 1 ticker.
- **Day 3** — VERIFY step + output formatting with citations. Harden error handling (missing filing, absent section, rate limit). Test on 3-4 tickers.
- **Day 4** — Minimal chat front end. Polish. Test several typical queries ("sector export-control risk", "analyze NVDA latest 10-K").
- **Day 5** — **5-min demo video** (filmed + edited by YOU alone, strict rule), **architecture diagram** (Foundry at center), README + project description. **Submit on the 13th, not the 14th.** Keep a margin.

---

## 9. Submission deliverables (regulation checklist)

- [ ] Working project with Microsoft Foundry
- [ ] **Public** GitHub repo with source code
- [ ] Demo video <= 5 min on YouTube/Vimeo (your exclusive work, no third-party music/brands without rights)
- [ ] Project description (features, problem solved, technologies)
- [ ] **Architecture diagram** showing Foundry usage
- [ ] Submitted via the "Projects" tab on the Contest Website

---

## 10. Pitfalls to avoid

- Do NOT scrape BIS / customs data on top — too fragile for 5 days. EDGAR alone is enough.
- Do NOT go for a real multi-agent. One agent + visible loop = same effect, zero fragility.
- Do NOT forget the EDGAR User-Agent (guaranteed 403 otherwise).
- Do NOT generate buy/sell advice (out of scope + loss of safety points).
- Do NOT rush the video + diagram: combined they're 30%+ of points, keep all of Day 5 for that.
- Cache filings locally for a demo that doesn't depend on the network during live presentation.
