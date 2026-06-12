"""
EDGAR client for SemiSignal.

Handles the two pitfalls that waste a morning:
  1. The User-Agent header (otherwise systematic 403)
  2. The 10 req/s rate limit (otherwise temporary block)

Everything is cached locally (SQLite) for a reliable demo with no network dependency.

Quick validation:
    python -m semisignal.edgar_client
"""

import datetime
import json
import re
import sqlite3
import threading
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from . import config

# --------------------------------------------------------------------------
# Simple rate limiter: guarantees a minimum interval between two requests.
# --------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, max_per_second: int):
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


_limiter = _RateLimiter(config.MAX_REQUESTS_PER_SECOND)
_session = requests.Session()
_session.headers.update({
    "User-Agent": config.USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
})


# --------------------------------------------------------------------------
# SQLite cache: url -> content. Avoids re-hitting EDGAR on every run.
# --------------------------------------------------------------------------
def _init_cache():
    con = sqlite3.connect(config.CACHE_DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS cache "
        "(url TEXT PRIMARY KEY, content TEXT, fetched_at REAL)"
    )
    con.commit()
    return con


def _get_cached(con, url: str) -> Optional[str]:
    row = con.execute("SELECT content FROM cache WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def _put_cached(con, url: str, content: str):
    con.execute(
        "INSERT OR REPLACE INTO cache (url, content, fetched_at) VALUES (?, ?, ?)",
        (url, content, time.time()),
    )
    con.commit()


def _fetch(url: str, con) -> str:
    """GET with cache + rate limit + User-Agent. Raises on 403/error."""
    cached = _get_cached(con, url)
    if cached is not None:
        return cached

    _limiter.wait()
    resp = _session.get(url, timeout=30)
    if resp.status_code == 403:
        raise RuntimeError(
            "403 EDGAR — check that USER_AGENT in config.py contains "
            "your real name + email."
        )
    resp.raise_for_status()
    _put_cached(con, url, resp.text)
    return resp.text


# --------------------------------------------------------------------------
# Ticker -> CIK resolution (dynamic, via the official SEC mapping).
# --------------------------------------------------------------------------
_TICKER_MAP = None


def resolve_cik(ticker: str, con) -> str:
    """Returns the zero-padded 10-digit CIK for a ticker."""
    global _TICKER_MAP
    if _TICKER_MAP is None:
        raw = _fetch("https://www.sec.gov/files/company_tickers.json", con)
        data = json.loads(raw)
        _TICKER_MAP = {
            entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
            for entry in data.values()
        }
    cik = _TICKER_MAP.get(ticker.upper())
    if cik is None:
        raise ValueError(f"Ticker not found in EDGAR: {ticker}")
    return cik


# --------------------------------------------------------------------------
# Filing list for a company (tool: list_filings).
# --------------------------------------------------------------------------
def list_filings(ticker: str, form_types: list, since_date: str = "2023-01-01",
                 con=None) -> list:
    """
    Returns recent filings for a ticker, filtered by form type.
    Each entry: {accession, form, filing_date, primary_document, cik}
    """
    own = con is None
    con = con or _init_cache()
    try:
        cik = resolve_cik(ticker, con)
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = json.loads(_fetch(url, con))
        recent = data["filings"]["recent"]

        results = []
        for i in range(len(recent["accessionNumber"])):
            form = recent["form"][i]
            date = recent["filingDate"][i]
            if form in form_types and date >= since_date:
                results.append({
                    "accession": recent["accessionNumber"][i],
                    "form": form,
                    "filing_date": date,
                    "primary_document": recent["primaryDocument"][i],
                    "cik": cik,
                })
        return results
    finally:
        if own:
            con.close()


# --------------------------------------------------------------------------
# Section fetch + extraction (tool: fetch_filing_section).
# --------------------------------------------------------------------------
def _filing_url(cik: str, accession: str, primary_document: str) -> str:
    acc_nodash = accession.replace("-", "")
    cik_int = int(cik)  # Archives path uses the CIK without zero-padding
    return (f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_int}/{acc_nodash}/{primary_document}")


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# Minimum block size to be considered real content (not a ToC entry).
_MIN_SECTION_CHARS = 2000
# Minimum offset before searching for the end marker (avoids false markers
# that appear immediately after the section header).
_MIN_END_OFFSET = 1000


# Inspection window for ToC detection (in characters).
_TOC_WINDOW = 500
# Number of DISTINCT item numbers in the window that signals a ToC.
# E.g. "Item 1A... Item 1B... Item 2... Item 3..." = 4 distinct -> ToC.
# Real prose rarely mentions 4+ different items within 500 chars.
_TOC_DISTINCT_THRESHOLD = 4

# Pattern to extract item numbers (e.g. "1A", "7", "3") —
# used by ToC detection heuristic 1.
_TOC_ITEM_NUM_PAT = re.compile(r"\bItem\s+(\d+\w*)", re.IGNORECASE)

# Typical page numbers (30-199): used by heuristic 2 to detect Intel-style
# ToCs that do not use "Item X" markers.
# E.g. "Risk Factors 37 Executive Officers 52 Market for Stock 53..."
_TOC_PAGE_NUM_PAT = re.compile(r"\b([3-9]\d|1\d{2})\b")
_TOC_PAGE_THRESHOLD = 4   # 4+ page numbers in 400 chars = ToC


def _is_toc_entry(text: str, pos: int) -> bool:
    """
    Returns True if position pos corresponds to a table-of-contents entry.

    Heuristic 1 (standard): high density of DISTINCT item numbers in the
    following window (Item 1A, Item 1B, Item 2, Item 3...).

    Heuristic 2 (Intel-style): many page numbers (30-199) in a short window.
    Intel formats its ToC as "Risk Factors 37\\nExecutive Officers 52" without
    "Item X" markers, which bypasses heuristic 1.
    """
    window = text[pos: pos + _TOC_WINDOW]
    # Heuristic 1: distinct item numbers
    distinct = set(_TOC_ITEM_NUM_PAT.findall(window))
    if len(distinct) >= _TOC_DISTINCT_THRESHOLD:
        return True
    # Heuristic 2: page numbers in short window
    page_nums = _TOC_PAGE_NUM_PAT.findall(window[:400])
    return len(page_nums) >= _TOC_PAGE_THRESHOLD


def _best_block(text: str, start_pats: list, end_pat) -> str:
    """
    Selects the best section block from all start candidates:

    1. Collects all candidates (union of start_pats), sorted by position.
    2. Filters out table-of-contents entries via _is_toc_entry.
    3. Among non-ToC candidates, computes the block up to end_pat and keeps
       the longest one that exceeds _MIN_SECTION_CHARS.
    4. Prefers blocks with an explicit end boundary (avoids EOF extension
       that artificially inflates block length).
    5. If all candidates look like ToC (cover document), falls back to the
       full set — the multi-file fallback will handle it if the result
       does not exceed _MIN_SECTION_CHARS.
    """
    seen: set = set()
    all_starts = []
    for pat in start_pats:
        for m in pat.finditer(text):
            if m.start() not in seen:
                seen.add(m.start())
                all_starts.append(m)

    if not all_starts:
        return ""

    all_starts.sort(key=lambda m: m.start())

    # Separate real section starts from ToC entries.
    non_toc = [m for m in all_starts if not _is_toc_entry(text, m.start())]
    # Fallback: if everything looks like a ToC (cover doc), keep all.
    candidates = non_toc if non_toc else all_starts

    best_bounded   = ""   # block with explicit end boundary
    best_unbounded = ""   # block extending to EOF (lower priority)

    for m in candidates:
        end_match = end_pat.search(text, m.start() + _MIN_END_OFFSET)
        if end_match:
            block = text[m.start():end_match.start()].strip()
            if len(block) > len(best_bounded):
                best_bounded = block
        else:
            block = text[m.start():].strip()
            if len(block) > len(best_unbounded):
                best_unbounded = block

    if len(best_bounded) >= _MIN_SECTION_CHARS:
        return best_bounded
    if len(best_unbounded) >= _MIN_SECTION_CHARS:
        return best_unbounded
    return ""


def extract_section(text: str, section_key: str, form_type: str = "10-K") -> str:
    """
    Robust section extraction using the "most substantial block" strategy.
    Supports US 10-K (Item 1A / Item 7) and foreign 20-F (Item 3.D / Item 5).

    Both item markers AND textual section titles are searched to maximize
    the chance of finding the real section start. See _best_block.
    """
    # re.MULTILINE makes ^ anchor to the start of each line.
    # Key effect: only matches "Item X" markers at line boundaries, which
    # excludes cross-references mid-sentence ("See Item 1A for details")
    # and inline navigation bars that would create false end-markers.
    ML = re.IGNORECASE | re.MULTILINE

    if form_type == "20-F":
        # 20-F structure (TSM, ASML...):
        #   Risk Factors -> Item 3.D (under "Item 3. Key Information")
        #   MD&A         -> Item 5 (Operating and Financial Review and Prospects)
        if section_key == "risk_factors":
            start_pats = [
                re.compile(r"^Item\s*3\.D[.\s]", ML),
                # Textual title fallback for unusually formatted 20-Fs
                re.compile(r"^risk\s+factors\s*$", ML),
            ]
            end_pat = re.compile(r"^Item\s*4\b", ML)
        else:  # mda
            start_pats = [
                re.compile(r"^Item\s*5[.\s]", ML),
            ]
            end_pat = re.compile(r"^Item\s*6\b", ML)
    else:
        # US 10-K structure (NVDA, AMD, INTC...)
        if section_key == "risk_factors":
            start_pats = [
                re.compile(r"^Item\s*1A[.\s]", ML),
                re.compile(r"^risk\s+factors\s*$", ML),
            ]
            end_pat = re.compile(r"^Item\s*1B\b|^Item\s*2\b", ML)
        else:  # mda
            start_pats = [
                re.compile(r"^Item\s*7[.\s]", ML),
                re.compile(r"^management.s\s+discussion\s+and\s+analysis", ML),
            ]
            end_pat = re.compile(r"^Item\s*7A\b|^Item\s*8\b", ML)

    return _best_block(text, start_pats, end_pat)


def _find_largest_htm_in_filing(cik: str, accession: str,
                                primary_doc: str, con) -> Optional[str]:
    """
    Parses the EDGAR filing index and returns the name of the largest .htm file,
    excluding the primary document and EDGAR infrastructure files
    (XBRL, exhibits, index). Fallback for multi-file filings (e.g. Intel).
    """
    acc_nodash = accession.replace("-", "")
    cik_int = int(cik)
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{acc_nodash}/{accession}-index.htm"
    )
    try:
        html = _fetch(index_url, con)
    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")
    best_doc  = None
    best_size = 0

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        # Find the first .htm link in the row
        link = None
        for cell in cells:
            a = cell.find("a", href=True)
            if a and a["href"].lower().endswith((".htm", ".html")):
                link = a
                break
        if not link:
            continue

        filename = link["href"].split("/")[-1]
        lower = filename.lower()
        # Exclude EDGAR infrastructure files and the primary document
        if any(x in lower for x in ("-index", "xbrl", "ex-", "r2.htm", "r3.htm")):
            continue
        if filename == primary_doc:
            continue

        # Size from the last cell (may be empty or malformatted)
        try:
            size = int(cells[-1].text.strip().replace(",", "").replace(" ", ""))
        except ValueError:
            size = 1  # unknown -> keep as candidate

        if size > best_size:
            best_size = size
            best_doc  = filename

    return best_doc


def fetch_filing_section(ticker: str, accession: str, primary_document: str,
                         cik: str, section_key: str, form_type: str = "10-K",
                         con=None) -> str:
    """Agent tool: fetches the text of a specific section from a filing.
    If the section is absent from the primary document, falls back to the
    largest alternative .htm file in the filing (multi-file filings, e.g. Intel).
    """
    own = con is None
    con = con or _init_cache()
    try:
        url = _filing_url(cik, accession, primary_document)
        html = _fetch(url, con)
        text = _html_to_text(html)
        section = extract_section(text, section_key, form_type)

        if not section:
            # Multi-file fallback: look for the largest .htm in the filing.
            alt_doc = _find_largest_htm_in_filing(cik, accession, primary_document, con)
            if alt_doc:
                alt_url = _filing_url(cik, accession, alt_doc)
                alt_text = _html_to_text(_fetch(alt_url, con))
                section = extract_section(alt_text, section_key, form_type)

        return section
    finally:
        if own:
            con.close()


# --------------------------------------------------------------------------
# Geopolitical scan (tool: scan_geopolitical_exposure).
# --------------------------------------------------------------------------
def scan_geopolitical_exposure(text: str) -> dict:
    """Returns a count per keyword + the sentences containing them."""
    counts = {}
    hits = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for kw in config.GEOPOLITICAL_KEYWORDS:
        pat = re.compile(re.escape(kw), re.IGNORECASE)
        c = len(pat.findall(text))
        if c:
            counts[kw] = c
    for s in sentences:
        if any(re.search(re.escape(kw), s, re.IGNORECASE)
               for kw in config.GEOPOLITICAL_KEYWORDS):
            hits.append(s.strip())
    return {"counts": counts, "passages": hits[:40]}


# --------------------------------------------------------------------------
# XBRL financial metric (tool: get_financial_metric).
# --------------------------------------------------------------------------

# The ASC 606 revenue recognition standard (~2018) caused most companies to
# stop reporting under the legacy "Revenues" tag and switch to the longer
# RevenueFromContractWithCustomer* tags. Without aliasing, querying "Revenues"
# for MU/AMAT/LRCX returns stale data from 2011-2019.
CONCEPT_ALIASES: dict = {
    "Revenues": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # ASC 606, modern
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",                                              # legacy tag
        "SalesRevenueNet",
    ],
}

# Values older than this many days are flagged as potentially stale.
_STALENESS_DAYS = 18 * 30   # ~18 months


def _fetch_best_annual(cik: str, concept: str, con) -> Optional[dict]:
    """
    Fetches the latest annual value (10-K / 20-F) for one us-gaap concept.
    Returns a result dict or None if the concept is absent / has no data.
    """
    url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
           f"CIK{cik}/us-gaap/{concept}.json")
    try:
        data = json.loads(_fetch(url, con))
    except Exception:
        return None

    units = data.get("units", {})
    unit_key = next(iter(units), None)
    if not unit_key:
        return None

    rows = units[unit_key]
    annual = [v for v in rows if v.get("form") in ("10-K", "20-F")]
    if not annual:
        annual = rows   # fall back to all periods if no annual filing found
    if not annual:
        return None

    last = sorted(annual, key=lambda v: v.get("end") or "")[-1]
    return {
        "value":        last.get("val"),
        "unit":         unit_key,
        "period_end":   last.get("end"),
        "form":         last.get("form"),
        "fiscal_year":  last.get("fy"),
        "concept_used": concept,
    }


def get_financial_metric(ticker: str, concept: str, con=None) -> dict:
    """
    Returns the latest annual value of a us-gaap XBRL concept.

    For concepts in CONCEPT_ALIASES (e.g. 'Revenues'), tries all candidate
    concepts and returns the one with the most recent period_end. This handles
    the ASC 606 transition (~2018) which caused many companies to abandon the
    legacy 'Revenues' tag in favour of RevenueFromContractWithCustomer*.

    Adds 'concept_used' to the result so the agent knows which tag was actually
    used, and 'stale'/'warning' if the best available data is older than 18 months.

    Example concepts: 'Revenues', 'NetIncomeLoss', 'ResearchAndDevelopmentExpense'.
    """
    own = con is None
    con = con or _init_cache()
    try:
        cik = resolve_cik(ticker, con)

        # Resolve to the ordered candidate list (or use the concept as-is).
        candidates = CONCEPT_ALIASES.get(concept, [concept])

        best: Optional[dict] = None
        for candidate in candidates:
            result = _fetch_best_annual(cik, candidate, con)
            if result is None:
                continue
            # Pick the candidate whose latest value has the most recent period end.
            if best is None or (result["period_end"] or "") > (best["period_end"] or ""):
                best = result

        if best is None:
            return {"concept": concept, "error": "concept not found for this ticker"}

        out: dict = {
            "concept":      concept,
            "concept_used": best["concept_used"],
            "value":        best["value"],
            "unit":         best["unit"],
            "period_end":   best["period_end"],
            "form":         best["form"],
            "fiscal_year":  best["fiscal_year"],
        }

        # Staleness check: flag values that are more than ~18 months old.
        try:
            period_date = datetime.date.fromisoformat(best["period_end"])
            cutoff = datetime.date.today() - datetime.timedelta(days=_STALENESS_DAYS)
            if period_date < cutoff:
                out["stale"] = True
                out["warning"] = (
                    f"potentially stale value — "
                    f"latest available data: {best['period_end']}"
                )
        except (ValueError, TypeError):
            pass

        return out
    finally:
        if own:
            con.close()


# --------------------------------------------------------------------------
# Demo / validation: run this module to verify EDGAR access + section parsing.
# Displays length and start of each section to detect ToC false positives.
# --------------------------------------------------------------------------
def _demo():
    import sys as _sys
    if hasattr(_sys.stdout, 'reconfigure'):
        _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    con = _init_cache()
    try:
        for ticker in ('NVDA', 'AMD', 'INTC'):
            print('\n' + '='*60)
            print('[' + ticker + ']')
            filings = list_filings(ticker, ['10-K'], con=con)
            if not filings:
                print('  WARN: no 10-K found for ' + ticker + ' (adjust since_date).')
                continue
            f = filings[0]
            print('  Latest 10-K  : ' + f['filing_date'] + ' (' + f['accession'] + ')')
            print('  Document     : ' + f['primary_document'])

            for section_key in ('risk_factors', 'mda'):
                section = fetch_filing_section(
                    ticker, f['accession'], f['primary_document'],
                    f['cik'], section_key, con=con,
                )
                nb = len(section)
                statut = 'OK' if nb >= _MIN_SECTION_CHARS else 'SHORT'
                print('  ' + section_key.ljust(15) + ' : ' + str(nb).rjust(7)
                      + ' chars  [' + statut + ']')
                if section:
                    apercu = section[:200].replace('\n', ' ')
                    print('    Start: ' + repr(apercu))
                else:
                    print('    Start: (empty - section not extracted)')

        print('\n' + '='*60)
        print('Goal: each section >= 2000 chars, start = real risk factor text.')
        print('Demo complete.')
    finally:
        con.close()


if __name__ == "__main__":
    _demo()
