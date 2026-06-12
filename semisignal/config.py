"""SemiSignal config — watchlist, EDGAR parameters, and Foundry deployment."""

# ============================================================================
# EDGAR
# ============================================================================

# ⚠️ REQUIRED: replace with your real name + email.
# Without this EDGAR returns a 403 on ALL requests.
USER_AGENT = "SemiSignal <yourmail@yourdomain.com>"

# EDGAR enforces a max of 10 requests/second. We keep a margin.
MAX_REQUESTS_PER_SECOND = 8

# ============================================================================
# FOUNDRY MODEL
# ============================================================================

# Name of the deployment created in the Foundry portal.
# Defaults to the model ID. If you kept the default name, leave as-is.
DEPLOYMENT_NAME = "claude-opus-4-8"

# Foundry credentials are read from environment variables
# (see .env.example): ANTHROPIC_FOUNDRY_API_KEY + ANTHROPIC_FOUNDRY_RESOURCE.
# The Anthropic SDK reads them automatically.

MAX_TOKENS = 4096          # max output tokens per call
MAX_AGENT_TURNS = 12       # safety limit against infinite tool-call loops

# ============================================================================
# WATCHLIST
# ============================================================================

# CIKs are resolved dynamically from the ticker (see edgar_client.resolve_cik),
# so there is no need to hard-code them.
# form_types: 10-K (US annual), 10-Q (US quarterly), 20-F (foreign annual).
WATCHLIST = [
    {"ticker": "NVDA", "form_types": ["10-K", "10-Q"]},
    {"ticker": "AMD",  "form_types": ["10-K", "10-Q"]},
    {"ticker": "INTC", "form_types": ["10-K", "10-Q"]},
    {"ticker": "AVGO", "form_types": ["10-K", "10-Q"]},
    {"ticker": "QCOM", "form_types": ["10-K", "10-Q"]},
    {"ticker": "MU",   "form_types": ["10-K", "10-Q"]},
    {"ticker": "AMAT", "form_types": ["10-K", "10-Q"]},
    {"ticker": "LRCX", "form_types": ["10-K", "10-Q"]},
    # Foreign issuers: file 20-F instead of 10-K.
    # Different structure (Item 3.D for Risk Factors, Item 5 for MD&A).
    # 20-F support added in edgar_client.extract_section.
    {"ticker": "TSM",  "form_types": ["20-F"]},
    {"ticker": "ASML", "form_types": ["20-F"]},
]

# Geopolitical / export-control keywords to scan in sections.
GEOPOLITICAL_KEYWORDS = [
    "export control", "export controls", "BIS", "entity list",
    "China", "Chinese", "Taiwan", "tariff", "tariffs", "sanction",
    "national security", "supply chain", "semiconductor equipment",
    "license requirement", "trade restriction",
]

# Sections to extract (never the full filing).
SECTIONS = {
    "risk_factors": "Item 1A",   # risk exposure incl. geopolitical — the gold mine
    "mda": "Item 7",             # Management's Discussion and Analysis
}

CACHE_DB = "edgar_cache.sqlite"
