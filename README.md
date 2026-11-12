Production-Grade Synthetic Order-to-Cash (O2C) Pipeline & Revenue Leakage Detection Engine

A comprehensive, production-grade synthetic data pipeline and analytics platform designed to model complex enterprise B2B Order-to-Cash (O2C) lifecycles, enforce relational integrity across 11 core entities, and detect revenue leakage with pristine 1.0000 Precision, Recall, and F1-Score.




Project Overview & Architecture

This project simulates a full enterprise ERP transaction flow—spanning customer master creation, commercial quoting, sales order conversion, warehouse fulfillment, billing generation, cash application, dispute management, and immutable state-machine tracking.

Built entirely from scratch with deterministic seeding (seed=20261022), the pipeline guarantees absolute reproducibility, cryptographic verification via SHA-256 manifests, and complete independence from external or restricted datasets.




Core Relational Schema (11 Tables)

accounts: Customer master record and AR sub-ledger balance summary (ACC-2026-XXXXXX).

quotes & quote_lines: Commercial proposals (QTE-2026-XXXXXX) and line items capturing contracted SKUs, pricing, and 30-day validity windows.

sales_orders & order_lines: Confirmed customer bookings (SO-2026-XXXXXX) converted from accepted quotes, tracking ordered vs. fulfilled quantities.

shipments: Warehouse fulfillment and dispatch records (SHP-2026-XXXXXX) tracking partial or full deliveries across multiple tranches.

invoices & invoice_lines: Billing documents (INV-2026-XXXXXX) generated from fulfilled quantities, tracking gross amounts, paid amounts, balance due, and aging days.

payments: Customer cash receipts and remittance allocations (PAY-2026-XXXXXX) applied against open invoice balances.

disputes: Customer support tickets (DSP-2026-XXXXXX) logging billing disagreements and AR sub-ledger hold synchronization.

status_events: Immutable audit ledger logging chronological state transitions across quotes and sales orders without overwriting history.



Targeted Anomaly & Leakage Coverage

The generator injects and isolates 5 specific negative scenarios alongside complex hard-negative edge cases:

INVOICE_EXCEEDS_FULFILLED_QTY: Overbilling anomalies where billed quantities exceed warehouse shipments.

PAYMENT_ALLOCATED_TWICE: Duplicate remittance entries resulting in unapplied overpayments.

ORDER_CLOSED_WITH_UNPAID_INVOICE: Premature sales order closure before complete cash settlement.

STATUS_EVENT_SKIPS_REQUIRED_STATE: Workflow state-machine bypasses violating required transition rules.

DISPUTE_NOT_REFLECTED_IN_AR: Support ticket disputes not synchronized to financial credit holds.

 
 
 
 Installation & Execution Workflow

Prerequisites

Python 3.10+

Pandas, Streamlit




Quick Start

Clone the repository and run the scripts in sequence:

# Step 1: Generate synthetic O2C data, multi-format exports, and SQL seed script
python generate_data.py

# Step 2: Run the 10-tier validation engine, leakage quantification, and anomaly detection
python validate_and_detect.py

# Step 3: Launch the interactive Streamlit executive dashboard
streamlit run app.py


 
 
 Evaluation & Validation Results
 Reproducibility Verified: Dual-pass checksum validation matches 100% across runs.Referential Integrity: 100% valid primary-to-foreign key mappings across all 22 cross-table relationships.Detection Accuracy: Pristine 1.0000 Precision, Recall, and F1-Score against isolated ground-truth labels across 255 benchmark anomalies.Financial Reconciliation: Exact monetary reconciliation with $0.00$ variance between computed balances and sub-ledger totals.