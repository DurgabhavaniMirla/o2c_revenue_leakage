import os
import json
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="O2C Revenue Leakage & Audit Dashboard",
    page_icon="📊",
    layout="wide"
)

DATA_DIR = "data"
OUTPUT_DIR = "output"

@st.cache_data
def load_pipeline_data():
    summary_path = os.path.join(OUTPUT_DIR, "validation_summary.json")
    exceptions_path = os.path.join(OUTPUT_DIR, "exceptions_and_decisions.csv")
    delays_path = os.path.join(OUTPUT_DIR, "process_delays.csv")
    
    summary = {}
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
            
    exceptions_df = pd.read_csv(exceptions_path) if os.path.exists(exceptions_path) else pd.DataFrame()
    delays_df = pd.read_csv(delays_path) if os.path.exists(delays_path) else pd.DataFrame()
    
    return summary, exceptions_df, delays_df

summary, exceptions_df, delays_df = load_pipeline_data()

st.title("📊 Order-to-Cash (O2C) Revenue Leakage & Audit Dashboard")
st.markdown("Automated synthetic data generation, relational validation, and financial anomaly detection engine.")

if not summary:
    st.error("Pipeline summary not found. Please run `python run_pipeline.py` first.")
else:
    fin_summary = summary.get("revenue_leakage_financial_summary", {})
    
    # Top Metrics Row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Order Book", f"₹{fin_summary.get('total_contracted_order_book_value', 0):,.2f}")
    with col2:
        st.metric("Detected Leakage", f"₹{fin_summary.get('detected_total_financial_exposure', 0):,.2f}")
    with col3:
        st.metric("Precision / Recall", f"{summary.get('precision', 0):.2f} / {summary.get('recall', 0):.2f}")
    with col4:
        st.metric("F1-Score", f"{summary.get('f1_score', 0):.4f}")

    st.markdown("---")

    # Financial Exposure Breakdown
    st.subheader("💡 Financial Impact Categories")
    b_col1, b_col2, b_col3 = st.columns(3)
    with b_col1:
        st.info(f"**Direct Revenue Leakage**\n\n₹{fin_summary.get('direct_revenue_leakage_amount', 0):,.2f}")
    with b_col2:
        st.warning(f"**Overbilling & Duplicates**\n\n₹{fin_summary.get('overbilling_and_duplicate_liability_amount', 0):,.2f}")
    with b_col3:
        st.error(f"**AR & Compliance Exposure**\n\n₹{fin_summary.get('ar_and_workflow_compliance_exposure_amount', 0):,.2f}")

    st.markdown("---")

    # Tabs for detailed exploration
    tab1, tab2, tab3 = st.tabs(["🔍 Detected Anomalies & Decisions", "⏳ Process Delays", "🛠️ Quality Gates Status"])

    with tab1:
        st.subheader("Exception Audit Log (`exceptions_and_decisions.csv`)")
        if not exceptions_df.empty:
            issue_filter = st.selectbox("Filter by Issue Type", ["All"] + list(exceptions_df["issue_type"].unique()))
            filtered_df = exceptions_df if issue_filter == "All" else exceptions_df[exceptions_df["issue_type"] == issue_filter]
            st.dataframe(filtered_df, use_container_width=True)
        else:
            st.warning("No exception records found.")

    with tab2:
        st.subheader("Flagged Process Delays (`process_delays.csv`) Orders (>10d delay / >60d aging)")
        if not delays_df.empty:
            st.dataframe(delays_df, use_container_width=True)
        else:
            st.success("No critical process delays flagged.")

    with tab3:
        st.subheader("10-Tier Quality Gates Audit")
        gates = summary.get("step8_schema_validation", {})
        st.json(gates)