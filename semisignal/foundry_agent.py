"""
SemiSignal core: the agent loop.

Calls Claude Opus 4.8 deployed on Microsoft Foundry (standard Messages API
format) and gives it access to the 4 EDGAR tools. The agent decomposes the
question, calls the tools, verifies, then synthesizes.

`run_agent()` is a GENERATOR: it yields steps in real-time so that Streamlit
can display the reasoning live (this is what wins the Reasoning Agents category).

Foundry auth: the Anthropic SDK reads these env variables (see .env):
    ANTHROPIC_FOUNDRY_API_KEY   <- key from "Keys and Endpoint" in the portal
    ANTHROPIC_FOUNDRY_RESOURCE  <- your Foundry resource name
"""

import json

from . import config, edgar_client

# --------------------------------------------------------------------------
# Foundry client. The SDK reads credentials from the environment.
# ⚠️ Check the exact class name in your version of the anthropic SDK
#    (AnthropicFoundry is the expected name, in line with AnthropicBedrock /
#    AnthropicVertex). If the import fails, run: pip install -U anthropic
# --------------------------------------------------------------------------
def _make_client():
    from anthropic import AnthropicFoundry  # noqa
    return AnthropicFoundry()  # reads ANTHROPIC_FOUNDRY_API_KEY + _RESOURCE


# --------------------------------------------------------------------------
# System prompt (same as in the portal, but this is the authoritative version
# when calling via the API).
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are SemiSignal, an expert semiconductor industry analyst.
You analyze SEC EDGAR filings (10-K, 10-Q, 20-F) to identify geopolitical and
export-control risks for semiconductor companies.

Always respond in English, regardless of the language of the user's question.
All reasoning steps (PLAN, RETRIEVE, GROUND, ANALYZE, VERIFY, SYNTHESIZE) and
the final note must be written in English.

Follow these 6 steps and announce each one with a short line starting with the
step name in capitals (PLAN:, RETRIEVE:, etc.) so the user can follow your
reasoning:

PLAN: decompose the request into subtasks.
RETRIEVE: use list_filings then fetch_filing_section / scan_geopolitical_exposure
  to get the relevant sections (always Item 1A Risk Factors, plus Item 7 MD&A
  when useful). When several companies are involved, gather each one.
GROUND: base every claim strictly on retrieved filing content.
ANALYZE: identify geopolitical signals; when multiple companies are involved,
  COMPARE them and surface sector-wide trends (this comparative angle is key).
VERIFY: challenge every claim. If it is not grounded in a filing, drop it or
  mark it as unverified.
SYNTHESIZE: produce a structured note. Cite every claim as
  [Source: TICKER FORM, SECTION, filed YYYY-MM-DD].

Rules:
- Never recommend buying or selling securities. You are a research tool.
- Never invent data not present in the filings.
- List unverified claims in a separate section.
- End with: "Research tool. Not investment advice."
- If a section cannot be extracted from a filing (the tool returns an error or
  empty content), do NOT retry the same section on the same company more than once.
  Note it as "section unavailable" and move on. Never call the same tool with the
  same arguments twice in a session.
"""

# --------------------------------------------------------------------------
# Tool definitions (Anthropic format). Deliberately simple surface:
# the model reasons with ticker + form_type + section; the rest (CIK,
# document, cache) is handled internally by edgar_client.
# --------------------------------------------------------------------------
TOOLS = [
    {
        "name": "list_filings",
        "description": "List recent filings for a company (date + type). "
                       "Use this to check what is available before reading one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "E.g.: NVDA, AMD, TSM"},
                "form_type": {"type": "string", "description": "10-K, 10-Q or 20-F"},
            },
            "required": ["ticker", "form_type"],
        },
    },
    {
        "name": "fetch_filing_section",
        "description": "Fetch the text of a specific section from the Nth most recent "
                       "filing. section: 'risk_factors' (Item 1A) or 'mda' (Item 7). "
                       "recency_index 0 = most recent, 1 = previous "
                       "(useful for year-over-year comparison).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "form_type": {"type": "string"},
                "section": {"type": "string", "enum": ["risk_factors", "mda"]},
                "recency_index": {"type": "integer", "default": 0},
            },
            "required": ["ticker", "form_type", "section"],
        },
    },
    {
        "name": "scan_geopolitical_exposure",
        "description": "Fetch a section then scan it for geopolitical keywords "
                       "(export controls, China, Taiwan, BIS...). "
                       "Returns a count per keyword + the relevant passages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "form_type": {"type": "string"},
                "section": {"type": "string", "enum": ["risk_factors", "mda"]},
                "recency_index": {"type": "integer", "default": 0},
            },
            "required": ["ticker", "form_type", "section"],
        },
    },
    {
        "name": "get_financial_metric",
        "description": "Latest annual value of an XBRL financial concept "
                       "(e.g.: Revenues, NetIncomeLoss, ResearchAndDevelopmentExpense).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "concept": {"type": "string"},
            },
            "required": ["ticker", "concept"],
        },
    },
]


# --------------------------------------------------------------------------
# Dispatch: execute a tool called by the model.
# --------------------------------------------------------------------------
def _resolve_filing(ticker, form_type, recency_index, con):
    filings = edgar_client.list_filings(ticker, [form_type], con=con)
    if not filings:
        return None
    idx = min(recency_index, len(filings) - 1)
    return filings[idx]


def _run_tool(name, args, con) -> str:
    try:
        if name == "list_filings":
            filings = edgar_client.list_filings(
                args["ticker"], [args["form_type"]], con=con)
            brief = [{"accession": f["accession"], "form": f["form"],
                      "filing_date": f["filing_date"]} for f in filings[:8]]
            return json.dumps(brief)

        if name in ("fetch_filing_section", "scan_geopolitical_exposure"):
            f = _resolve_filing(args["ticker"], args["form_type"],
                                args.get("recency_index", 0), con)
            if not f:
                return json.dumps({"error": "no filing found"})
            # Pass the actual form type so extract_section chooses the right
            # markers (10-K vs 20-F).
            text = edgar_client.fetch_filing_section(
                args["ticker"], f["accession"], f["primary_document"],
                f["cik"], args["section"], form_type=f["form"], con=con)
            if not text:
                return json.dumps({"error": "section could not be extracted (parsing)"})
            meta = {"ticker": args["ticker"], "form": f["form"],
                    "filing_date": f["filing_date"], "section": args["section"]}
            if name == "fetch_filing_section":
                # Truncate to keep token usage reasonable.
                return json.dumps({**meta, "text": text[:18000]})
            scan = edgar_client.scan_geopolitical_exposure(text)
            return json.dumps({**meta, **scan})

        if name == "get_financial_metric":
            return json.dumps(edgar_client.get_financial_metric(
                args["ticker"], args["concept"], con=con))

        return json.dumps({"error": f"unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# --------------------------------------------------------------------------
# Agent loop. Generator: yields ("STEP", text) then ("FINAL", note).
# --------------------------------------------------------------------------
def run_agent(question: str):
    client = _make_client()
    con = edgar_client._init_cache()
    messages = [{"role": "user", "content": question}]
    # Anti-loop guard: track call signatures (tool + args) already executed.
    # If the model calls the same tool with the same arguments, short-circuit.
    _signatures_vues: set = set()

    try:
        for _ in range(config.MAX_AGENT_TURNS):
            resp = client.messages.create(
                model=config.DEPLOYMENT_NAME,
                max_tokens=config.MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Display reasoning text produced this turn.
            for block in resp.content:
                if block.type == "text" and block.text.strip():
                    yield ("REASONING", block.text.strip())

            if resp.stop_reason != "tool_use":
                # Final response: assemble the text.
                final = "\n".join(b.text for b in resp.content if b.type == "text")
                yield ("FINAL", final)
                return

            # Otherwise: execute the requested tools and return results.
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    yield ("TOOL", f"{block.name}({json.dumps(block.input)})")
                    # Deduplication: same tool + same args -> immediate response.
                    signature = f"{block.name}:{json.dumps(block.input, sort_keys=True)}"
                    if signature in _signatures_vues:
                        result = json.dumps({
                            "error": "already attempted — section unavailable, do not retry"
                        })
                    else:
                        _signatures_vues.add(signature)
                        result = _run_tool(block.name, block.input, con)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})

        yield ("FINAL", "Warning: turn limit reached (MAX_AGENT_TURNS).")
    finally:
        con.close()
