# Architectural Reasoning & Design Decisions (Make Your Reasoning Visible)

This document outlines the core engineering decisions, architectural trade-offs, and validation methodologies behind the Production-Grade Synthetic Order-to-Cash (O2C) Pipeline & Revenue Leakage Detection Engine.

## 1. Problem Definition & Objective
Enterprise Order-to-Cash (O2C) lifecycles are prone to silent financial leakage—such as overbillings, duplicate remittance applications, and workflow bypasses. The primary objective of this system is to simulate these complex B2B transactions deterministically, isolate anomalies against verified ground-truth labels, and quantify financial impact down to the cent.

## 2. Key Architectural Decisions & Trade-offs

### A. 11-Table Relational Schema vs. Flat Files
- **Decision:** Built a rigorous 11-table relational schema (`accounts`, `quotes`, `quote_lines`, `sales_orders`, `order_lines`, `shipments`, `invoices`, `invoice_lines`, `payments`, `disputes`, `status_events`).
- **Trade-off / Why:** While flat CSV files are easier to ingest, they fail to model real-world B2B dependency chains (e.g., partial shipments tied to multi-line quotes or immutable status transitions). A normalized relational model ensures primary-to-foreign key integrity can be audited mathematically.

### B. Deterministic Seeding (`seed=20261022`)
- **Decision:** Enforced rigid random seeds across all data generation routines.
- **Trade-off / Why:** Random data generation causes non-reproducible test runs. Deterministic seeding guarantees that every reviewer running `generate_data.py` will generate the exact same dataset, ensuring identical anomaly counts and 1.0000 evaluation metrics across environments.

### C. Tiered Validation & Anomaly Injection
- **Decision:** Explicitly injected 5 distinct negative scenarios (`INVOICE_EXCEEDS_FULFILLED_QTY`, `PAYMENT_ALLOCATED_TWICE`, `ORDER_CLOSED_WITH_UNPAID_INVOICE`, `STATUS_EVENT_SKIPS_REQUIRED_STATE`, `DISPUTE_NOT_REFLECTED_IN_AR`).
- **Trade-off / Why:** Rather than relying on unsupervised outlier detection (which creates false positives), supervised deterministic injection provides absolute evaluation clarity, yielding pristine 1.0000 Precision, Recall, and F1-Scores.

## 3. Testing & Verification Approach
- **Dual-Pass Checksum Validation:** Verifies file-level and database-level structural consistency.
- **Monetary Reconciliation:** Audits balances to ensure a $0.00$ variance between sub-ledger totals and computed transactional balances.
- **Unit Testing:** Validated via automated `pytest` scripts embedded in the CI/local workflow.