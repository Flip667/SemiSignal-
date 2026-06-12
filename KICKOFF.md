# KICKOFF — SemiSignal

> Current status: the Foundry gate is CLEARED. Azure account active,
> Claude Opus 4.8 deployed, agent created. All that remains is to connect and test.

---

## Locked decisions

| Topic | Decision |
|---|---|
| Track | Reasoning Agents (Microsoft Foundry) |
| Model | **Claude Opus 4.8** (deployed, Global Standard) — best available |
| Call | Anthropic SDK pointed at the Foundry endpoint, custom tool-use loop |
| Front | Streamlit, with live reasoning display |
| Data | EDGAR corpus frozen + cached locally |
| Sections | Item 1A (Risk Factors) + Item 7 (MD&A) only |
| Differentiator | **Multi-filing comparative analysis** |

> Note: the agent registered in the Foundry portal serves visibility + the
> "uses Foundry" checkbox in the rules. The actual runtime is your Python code
> calling the Opus 4.8 deployment (Claude is not driven by the native Agent Service,
> so we orchestrate the loop ourselves — simpler and more reliable).

---

## Remaining steps

### 1. EDGAR quick win (no Foundry required)
- [ ] `pip install -r requirements.txt`
- [ ] Set your **real name + email** in `semisignal/config.py` (USER_AGENT)
- [ ] `python -m semisignal.edgar_client` -> should output the NVDA 10-K + geo scan

### 2. Connect Foundry
- [ ] `cp .env.example .env`
- [ ] In the Foundry portal -> your resource -> **Keys and Endpoint**:
      copy the key into `ANTHROPIC_FOUNDRY_API_KEY` and the resource name
      into `ANTHROPIC_FOUNDRY_RESOURCE` (in `.env`)
- [ ] Check that `DEPLOYMENT_NAME` in config.py = your deployment name
      (default: `claude-opus-4-8`)

### 3. Launch the app
- [ ] `streamlit run app.py`
- [ ] Ask a real question -> watch the agent run PLAN -> ... -> SYNTHESIZE
      while calling the EDGAR tools

### 4. Iterate (Days 2-3)
- [ ] Refine the system prompt in `foundry_agent.py` based on what you observe
- [ ] Push the comparative analysis (cross multiple companies)
- [ ] Sharpen the VERIFY step (refusing to invent = reliability points)

### 5. Delivery (Day 5, submit on the 13th)
- [ ] 5-min demo video (filmed + edited by you alone)
- [ ] Diagram (already done: architecture.mermaid -> export to PNG)
- [ ] README (already filled in) + video link
- [ ] Public GitHub repo + submission

---

## Reminders that save the day

1. **EDGAR User-Agent required** (name + email) — otherwise 403
2. **Never commit `.env`** (already in .gitignore)
3. **Azure budget**: set an alert in Cost Management (~$80)
4. **Opus 4.8 = $5/$25 per M tokens** -> ~$30-50 for the whole hackathon with caching
5. **No buy/sell advice** -> analysis tool only
6. **Submit on the 13th**, keep +24h margin for the Discord vote

---

## Fallbacks

- **`AnthropicFoundry` import fails** -> `pip install -U anthropic`, and check
  the exact Foundry class name in your SDK version's docs
- **Section parser broken on a filing** -> keep 3-4 filings that parse cleanly
  and run your demo on those
- **Foundry quota / rate limit (429)** -> the app retries; otherwise space out
  requests or request a quota increase in Azure
