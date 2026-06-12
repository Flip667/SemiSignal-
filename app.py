"""
SemiSignal — Streamlit interface.

Launch: streamlit run app.py

Displays the agent's reasoning LIVE (steps + tool calls), not just the final
report. This is what judges in the Reasoning category want to see.

Prerequisites: Foundry env variables must be loaded (see .env.example).
"""

import streamlit as st

from semisignal import foundry_agent

st.set_page_config(page_title="SemiSignal", page_icon="🔎", layout="wide")
st.title("🔎 SemiSignal")
st.caption("Semiconductor analyst agent — SEC EDGAR · Claude Opus 4.8 on Microsoft Foundry")
st.warning("Research tool. Not investment advice.", icon="⚠️")

with st.expander("Sample questions"):
    st.markdown(
        "- How has NVIDIA's export-control exposure to China evolved "
        "between its latest 10-K and the previous one?\n"
        "- Compare the geopolitical risks cited by NVDA, AMD, and INTC "
        "in their latest 10-K filings.\n"
        "- What Taiwan-related risks does TSMC disclose in its 20-F?"
    )

query = st.text_input("Question", placeholder="Ask a question about the semiconductor sector...")

STEP_STYLE = {
    "REASONING": ("🧠", "Reasoning"),
    "TOOL":      ("🔧", "Tool call"),
    "FINAL":     ("📄", "Final note"),
}

if st.button("Analyze", type="primary") and query:
    col_steps, col_report = st.columns([1, 1])
    final_note = None

    with col_steps:
        st.subheader("Live reasoning")
        try:
            for step, detail in foundry_agent.run_agent(query):
                if step == "FINAL":
                    final_note = detail
                    continue
                icon, label = STEP_STYLE.get(step, ("•", step))
                with st.chat_message("assistant"):
                    st.markdown(f"{icon} **{label}**\n\n{detail}")
        except Exception as e:
            st.error(f"Agent error: {e}")
            st.info("Check your Foundry env variables and the deployment name "
                    "in config.py.")

    with col_report:
        st.subheader("📄 Report")
        if final_note:
            st.markdown(final_note)
        else:
            st.info("The final report will appear here once reasoning is complete.")
