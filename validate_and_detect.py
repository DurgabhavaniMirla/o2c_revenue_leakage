import os
import json
import hashlib
import pandas as pd
from generate_data import O2CSyntheticGenerator

class O2CValidatorAndDetector:
    def __init__(
        self,
        data_dir: str = "data",
        output_dir: str = "output",
        cutoff_date: str = "2026-10-31",
        seed: int = 20261022,
        scale: float = 1.0
    ):
        self.data_dir = data_dir
        self.output_dir = output_dir
        self.cutoff_dt = pd.to_datetime(cutoff_date)
        self.cutoff_str = cutoff_date
        self.seed = seed
        self.scale = scale

    def _compute_manifest(self):
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        csv_files = [f for f in sorted(os.listdir(self.data_dir)) if f.endswith(".csv")]
        if len(csv_files) < 11:
            O2CSyntheticGenerator(
                seed=self.seed, scale=self.scale, cutoff_date=self.cutoff_str
            ).generate_all(self.data_dir, self.output_dir)
            csv_files = [f for f in sorted(os.listdir(self.data_dir)) if f.endswith(".csv")]

        manifest = {"seed": self.seed, "row_counts": {}, "sha256_checksums": {}}
        for fname in csv_files:
            fpath = os.path.join(self.data_dir, fname)
            df_tmp = pd.read_csv(fpath)
            manifest["row_counts"][fname] = len(df_tmp)
            with open(fpath, "rb") as bf:
                manifest["sha256_checksums"][fname] = hashlib.sha256(bf.read()).hexdigest()
        return manifest

    def run_pipeline(self) -> dict:
        print(f"[*] Step 10: Verifying deterministic reproducibility across two runs (Seed: {self.seed})...")
        manifest_run1 = self._compute_manifest()
        O2CSyntheticGenerator(
            seed=self.seed, scale=self.scale, cutoff_date=self.cutoff_str
        ).generate_all(self.data_dir, self.output_dir)
        manifest_run2 = self._compute_manifest()
        reproducible = (
            manifest_run1["row_counts"] == manifest_run2["row_counts"]
            and manifest_run1["sha256_checksums"] == manifest_run2["sha256_checksums"]
        )
        manifest_run2["reproducibility_verified_across_two_runs"] = reproducible

        with open(os.path.join(self.output_dir, "source_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest_run2, f, indent=2)

        print("[*] Step 8: Running exhaustive 11-table PK/FK integrity, date chronology, workflow, and financial leakage quantification...")
        accounts = pd.read_csv(os.path.join(self.data_dir, "accounts.csv"))
        quotes = pd.read_csv(os.path.join(self.data_dir, "quotes.csv"))
        quote_lines = pd.read_csv(os.path.join(self.data_dir, "quote_lines.csv"))
        orders = pd.read_csv(os.path.join(self.data_dir, "sales_orders.csv"))
        order_lines = pd.read_csv(os.path.join(self.data_dir, "order_lines.csv"))
        shipments = pd.read_csv(os.path.join(self.data_dir, "shipments.csv"))
        invoices = pd.read_csv(os.path.join(self.data_dir, "invoices.csv"))
        invoice_lines = pd.read_csv(os.path.join(self.data_dir, "invoice_lines.csv"))
        payments = pd.read_csv(os.path.join(self.data_dir, "payments.csv"))
        disputes = pd.read_csv(os.path.join(self.data_dir, "disputes.csv"))
        status_events = pd.read_csv(os.path.join(self.data_dir, "status_events.csv"), keep_default_na=False)
        gt_df = pd.read_csv(os.path.join(self.output_dir, "ground_truth.csv"))

        pk_checks = {
            "accounts_pk_unique": bool(accounts["account_id"].is_unique),
            "quotes_pk_unique": bool(quotes["quote_id"].is_unique),
            "quote_lines_pk_unique": bool(quote_lines["quote_line_id"].is_unique),
            "sales_orders_pk_unique": bool(orders["order_id"].is_unique),
            "order_lines_pk_unique": bool(order_lines["order_line_id"].is_unique),
            "shipments_pk_unique": bool(shipments["shipment_line_id"].is_unique),
            "invoices_pk_unique": bool(invoices["invoice_id"].is_unique),
            "invoice_lines_pk_unique": bool(invoice_lines["invoice_line_id"].is_unique),
            "payments_pk_unique": bool(payments["payment_id"].is_unique),
            "disputes_pk_unique": bool(disputes["dispute_id"].is_unique),
            "status_events_pk_unique": bool(status_events["event_id"].is_unique)
        }

        acc_ids = set(accounts["account_id"])
        qte_ids = set(quotes["quote_id"])
        ord_ids = set(orders["order_id"])
        oln_ids = set(order_lines["order_line_id"])
        inv_ids = set(invoices["invoice_id"])

        q_events = status_events[status_events["entity_type"] == "Quote"]
        so_events = status_events[status_events["entity_type"] == "SalesOrder"]

        q_to_acc = dict(zip(quotes["quote_id"], quotes["account_id"]))
        ord_to_acc = dict(zip(orders["order_id"], orders["account_id"]))
        inv_to_acc = dict(zip(invoices["invoice_id"], invoices["account_id"]))
        inv_to_order = dict(zip(invoices["invoice_id"], invoices["order_id"]))
        inv_to_total = dict(zip(invoices["invoice_id"], invoices["invoice_total"]))
        ord_to_total = dict(zip(orders["order_id"], orders["order_total"]))
        oln_to_order = dict(zip(order_lines["order_line_id"], order_lines["order_id"]))

        fk_details = {
            "quotes_account_id_in_accounts": bool(quotes["account_id"].isin(acc_ids).all()),
            "quote_lines_quote_id_in_quotes": bool(quote_lines["quote_id"].isin(qte_ids).all()),
            "sales_orders_quote_id_in_quotes": bool(orders["quote_id"].isin(qte_ids).all()),
            "sales_orders_account_id_in_accounts": bool(orders["account_id"].isin(acc_ids).all()),
            "order_lines_order_id_in_sales_orders": bool(order_lines["order_id"].isin(ord_ids).all()),
            "shipments_order_id_in_sales_orders": bool(shipments["order_id"].isin(ord_ids).all()),
            "shipments_order_line_id_in_order_lines": bool(shipments["order_line_id"].isin(oln_ids).all()),
            "invoices_order_id_in_sales_orders": bool(invoices["order_id"].isin(ord_ids).all()),
            "invoices_account_id_in_accounts": bool(invoices["account_id"].isin(acc_ids).all()),
            "invoice_lines_invoice_id_in_invoices": bool(invoice_lines["invoice_id"].isin(inv_ids).all()),
            "invoice_lines_order_line_id_in_order_lines": bool(invoice_lines["order_line_id"].isin(oln_ids).all()),
            "payments_invoice_id_in_invoices": bool(payments["invoice_id"].isin(inv_ids).all()),
            "payments_account_id_in_accounts": bool(payments["account_id"].isin(acc_ids).all()),
            "disputes_invoice_id_in_invoices": bool(disputes["invoice_id"].isin(inv_ids).all()),
            "disputes_account_id_in_accounts": bool(disputes["account_id"].isin(acc_ids).all()),
            "status_events_polymorphic_entity_id_valid": bool(
                q_events["entity_id"].isin(qte_ids).all()
                and so_events["entity_id"].isin(ord_ids).all()
                and status_events["entity_type"].isin(["Quote", "SalesOrder", "Shipment", "Invoice", "Payment", "Dispute"]).all()
            ),
            "order_account_matches_quote_account": bool(
                (orders["account_id"] == orders["quote_id"].map(q_to_acc)).all()
            ),
            "invoice_account_matches_order_account": bool(
                (invoices["account_id"] == invoices["order_id"].map(ord_to_acc)).all()
            ),
            "payment_account_matches_invoice_account": bool(
                (payments["account_id"] == payments["invoice_id"].map(inv_to_acc)).all()
            ),
            "dispute_account_matches_invoice_account": bool(
                (disputes["account_id"] == disputes["invoice_id"].map(inv_to_acc)).all()
            ),
            "shipment_order_matches_order_line_order": bool(
                (shipments["order_id"] == shipments["order_line_id"].map(oln_to_order)).all()
            ),
            "invoice_line_order_matches_invoice_header_order": bool(
                (invoice_lines["order_line_id"].map(oln_to_order) == invoice_lines["invoice_id"].map(inv_to_order)).all()
            )
        }

        q_acc = quotes.merge(accounts[["account_id", "created_date"]], on="account_id", how="left")
        chk_acc_to_quote = bool(
            (pd.to_datetime(q_acc["quote_date"]) >= pd.to_datetime(q_acc["created_date"])).all()
            and (pd.to_datetime(q_acc["valid_until"]) >= pd.to_datetime(q_acc["quote_date"])).all()
        )

        ord_q = orders.merge(quotes[["quote_id", "quote_date", "valid_until"]], on="quote_id", how="left")
        chk_quote_to_order = bool(
            (pd.to_datetime(ord_q["order_date"]) >= pd.to_datetime(ord_q["quote_date"])).all()
            and (pd.to_datetime(ord_q["order_date"]) <= pd.to_datetime(ord_q["valid_until"])).all()
        )

        shp_ord = shipments.merge(orders[["order_id", "order_date"]], on="order_id", how="left")
        chk_order_to_ship = bool(
            (pd.to_datetime(shp_ord["ship_date"]) >= pd.to_datetime(shp_ord["order_date"])).all()
        )

        shp_max_by_line = shipments.groupby("order_line_id", as_index=False)["ship_date"].max()
        il_inv_shp = invoice_lines.merge(invoices[["invoice_id", "invoice_date", "due_date"]], on="invoice_id", how="left").merge(
            shp_max_by_line, on="order_line_id", how="left"
        )
        chk_ship_to_invoice = bool(
            (pd.to_datetime(il_inv_shp["invoice_date"]) >= pd.to_datetime(il_inv_shp["ship_date"])).all()
            and (pd.to_datetime(invoices["due_date"]) >= pd.to_datetime(invoices["invoice_date"])).all()
        )

        pay_inv = payments.merge(invoices[["invoice_id", "invoice_date"]], on="invoice_id", how="left")
        chk_invoice_to_payment = bool(
            (pd.to_datetime(pay_inv["payment_date"]) >= pd.to_datetime(pay_inv["invoice_date"])).all()
        )

        dsp_inv = disputes.merge(invoices[["invoice_id", "invoice_date"]], on="invoice_id", how="left")
        chk_invoice_to_dispute = bool(
            (pd.to_datetime(dsp_inv["dispute_date"]) >= pd.to_datetime(dsp_inv["invoice_date"])).all()
        )

        ev_sorted = status_events.copy()
        ev_sorted["parsed_ts"] = pd.to_datetime(ev_sorted["event_timestamp"])
        ev_sorted = ev_sorted.sort_values(["entity_type", "entity_id", "parsed_ts", "event_id"])
        chk_event_timestamps = bool(
            ev_sorted.groupby(["entity_type", "entity_id"])["parsed_ts"].is_monotonic_increasing.all()
        )

        ALLOWED_TRANSITIONS = {
            "Quote": {
                ("NULL", "Draft"),
                ("NULL", "Accepted"), ("NULL", "Sent"), ("NULL", "Rejected"), ("NULL", "Expired"),
                ("Draft", "Sent"), ("Draft", "Accepted"), ("Draft", "Rejected"), ("Draft", "Expired"),
                ("Sent", "Accepted"), ("Sent", "Rejected"), ("Sent", "Expired")
            },
            "SalesOrder": {
                ("NULL", "Created"),
                ("Created", "Fulfilled"),
                ("Created", "Partially_Fulfilled"),
                ("Partially_Fulfilled", "Fulfilled"),
                ("Partially_Fulfilled", "Invoiced"),
                ("Fulfilled", "Invoiced"),
                ("Invoiced", "Closed")
            }
        }

        order_status_map = dict(zip(orders["order_id"], orders["order_status"]))
        quote_status_map = dict(zip(quotes["quote_id"], quotes["quote_status"]))

        workflow_bypass_entities = []
        continuity_breaks = 0
        terminal_state_mismatches = 0

        for (e_type, e_id), grp in ev_sorted.groupby(["entity_type", "entity_id"], sort=False):
            if e_type not in ALLOWED_TRANSITIONS:
                continue
            allowed_set = ALLOWED_TRANSITIONS.get(e_type, set())
            prev_to = None
            has_bypass = False

            for _, row in grp.iterrows():
                f_st = row["from_state"] if row["from_state"] != "" else "NULL"
                t_st = row["to_state"]

                if prev_to is not None and f_st != prev_to:
                    continuity_breaks += 1
                prev_to = t_st

                if (f_st, t_st) not in allowed_set:
                    has_bypass = True

            if e_type == "SalesOrder":
                visited_states = set(grp["to_state"])
                if ("Invoiced" in visited_states or "Closed" in visited_states) and not (
                    {"Fulfilled", "Partially_Fulfilled"} & visited_states
                ):
                    has_bypass = True

                if prev_to != order_status_map.get(e_id):
                    terminal_state_mismatches += 1
            elif e_type == "Quote":
                if prev_to != quote_status_map.get(e_id):
                    terminal_state_mismatches += 1

            if has_bypass:
                workflow_bypass_entities.append(e_id)

        workflow_audit_checks = {
            "state_chain_continuity_intact": continuity_breaks == 0,
            "terminal_event_matches_entity_status": terminal_state_mismatches == 0,
            "illegal_workflow_bypasses_detected": len(workflow_bypass_entities)
        }

        date_chronology_checks = {
            "account_created_le_quote_date_le_valid_until": chk_acc_to_quote,
            "quote_date_le_order_date_le_valid_until": chk_quote_to_order,
            "order_date_le_ship_date": chk_order_to_ship,
            "ship_date_le_invoice_date_le_due_date": chk_ship_to_invoice,
            "invoice_date_le_payment_date": chk_invoice_to_payment,
            "invoice_date_le_dispute_date": chk_invoice_to_dispute,
            "status_event_timestamps_monotonic": chk_event_timestamps,
            "all_cross_table_date_rules_passed": all([
                chk_acc_to_quote, chk_quote_to_order, chk_order_to_ship,
                chk_ship_to_invoice, chk_invoice_to_payment, chk_invoice_to_dispute, chk_event_timestamps
            ])
        }

        ql_sum_by_q = quote_lines.groupby("quote_id")["line_total"].sum().round(2).reset_index()
        q_ql_reconciled = quotes.merge(ql_sum_by_q, on="quote_id", how="left").fillna({"line_total": 0.0})
        quote_lines_reconcile_to_header = bool(
            q_ql_reconciled["quote_total"].round(2).equals(q_ql_reconciled["line_total"].round(2))
        )

        ol_sum_by_ord = order_lines.groupby("order_id")["line_total"].sum().round(2).reset_index()
        ord_ol_reconciled = orders.merge(ol_sum_by_ord, on="order_id", how="left").fillna({"line_total": 0.0})
        order_lines_reconcile_to_header = bool(
            ord_ol_reconciled["order_total"].round(2).equals(ord_ol_reconciled["line_total"].round(2))
        )

        il_sum_by_inv = invoice_lines.groupby("invoice_id")["line_total"].sum().round(2).reset_index()
        inv_il_reconciled = invoices.merge(il_sum_by_inv, on="invoice_id", how="left").fillna({"line_total": 0.0})
        invoice_lines_reconcile_to_header = bool(
            inv_il_reconciled["invoice_total"].round(2).equals(inv_il_reconciled["line_total"].round(2))
        )

        pay_agg = payments.groupby("invoice_id").agg(
            independent_paid_sum=("amount", lambda s: round(s.sum(), 2)),
            payment_count=("payment_id", "count"),
            latest_payment_id=("payment_id", "last")
        ).reset_index()
        inv_pay_audit = invoices.merge(pay_agg, on="invoice_id", how="left").fillna(
            {"independent_paid_sum": 0.0, "payment_count": 0}
        )
        inv_pay_audit["unapplied_overpayment"] = (
            inv_pay_audit["independent_paid_sum"] - inv_pay_audit["invoice_total"]
        ).round(2)
        inv_pay_audit["computed_net_balance"] = (
            inv_pay_audit["invoice_total"] - inv_pay_audit["independent_paid_sum"]
        ).round(2)

        clean_pay_rows = inv_pay_audit[inv_pay_audit["unapplied_overpayment"] <= 0.0]
        independent_payment_ledger_reconciled = bool(
            clean_pay_rows["computed_net_balance"].equals(clean_pay_rows["balance_due"].round(2))
        )

        inv_ar_by_acc = invoices.groupby("account_id")["balance_due"].sum().round(2).reset_index()
        acc_ar_audit = accounts.merge(inv_ar_by_acc, on="account_id", how="left").fillna({"balance_due": 0.0})
        ar_subledger_reconciled = bool(
            acc_ar_audit["ar_balance"].round(2).equals(acc_ar_audit["balance_due"].round(2))
        )

        shp_header_consistency = bool(
            shipments.groupby("shipment_id")["order_id"].nunique().max() == 1
            and shipments.groupby("shipment_id")["ship_date"].nunique().max() == 1
            and shipments.groupby("shipment_id")["shipment_status"].nunique().max() == 1
        )

        schema_checks = {
            "primary_key_uniqueness": all(pk_checks.values()),
            "primary_key_details": pk_checks,
            "foreign_key_integrity": all(fk_details.values()),
            "foreign_key_relationship_details": fk_details,
            "shipment_header_granularity_consistent": shp_header_consistency,
            "allowed_enums_valid": bool(
                accounts["segment"].isin(["Enterprise", "Mid-Market", "SMB"]).all()
                and quotes["quote_status"].isin(["Draft", "Sent", "Accepted", "Rejected", "Expired"]).all()
                and orders["order_status"].isin(["Created", "Fulfilled", "Partially_Fulfilled", "Invoiced", "Closed"]).all()
                and shipments["shipment_status"].isin(["Delivered", "Partial"]).all()
                and invoices["invoice_status"].isin(["Issued", "Paid", "Overdue", "Disputed"]).all()
                and payments["payment_status"].isin(["Allocated", "Duplicate_Allocation"]).all()
                and disputes["dispute_status"].isin(["Open", "Resolved"]).all()
            ),
            "date_ordering_valid": date_chronology_checks["all_cross_table_date_rules_passed"],
            "cross_table_date_chronology_details": date_chronology_checks,
            "o2c_workflow_state_machine_audit": workflow_audit_checks,
            "arithmetic_reconciliation_valid": bool(
                (quote_lines["quantity"] * quote_lines["unit_price"]).round(2).equals(quote_lines["line_total"].round(2))
                and (order_lines["ordered_qty"] * order_lines["unit_price"]).round(2).equals(order_lines["line_total"].round(2))
                and (invoice_lines["invoiced_qty"] * invoice_lines["unit_price"]).round(2).equals(invoice_lines["line_total"].round(2))
                and quote_lines_reconcile_to_header
                and order_lines_reconcile_to_header
                and invoice_lines_reconcile_to_header
            ),
            "invoice_lines_reconcile_to_invoice_header": invoice_lines_reconcile_to_header,
            "independent_payment_ledger_reconciled": independent_payment_ledger_reconciled,
            "account_ar_subledger_reconciled": ar_subledger_reconciled
        }

        detected_anomalies = []

        shp_totals = shipments.groupby("order_line_id", as_index=False).agg(
            shipped_qty=("shipped_qty", "sum"),
            last_ship_date=("ship_date", "max")
        )
        total_invoiced_by_line = invoice_lines.groupby("order_line_id")["invoiced_qty"].sum().to_dict()
        shipped_by_line = dict(zip(shp_totals["order_line_id"], shp_totals["shipped_qty"]))

        il_with_header = invoice_lines.merge(
            invoices[["invoice_id", "order_id", "invoice_date", "invoice_total", "invoice_status"]],
            on="invoice_id", how="left"
        )
        candidate_dup_il = il_with_header[
            il_with_header.duplicated(
                subset=["order_id", "order_line_id", "invoiced_qty", "unit_price", "invoice_date"],
                keep="first"
            )
        ]
        dup_invoice_ids = set()
        for _, row in candidate_dup_il.iterrows():
            ol_id = row["order_line_id"]
            if (
                total_invoiced_by_line.get(ol_id, 0) > shipped_by_line.get(ol_id, 0)
                and row["invoice_status"] != "Voided"
            ):
                dup_invoice_ids.add(row["invoice_id"])

        for inv_id in sorted(dup_invoice_ids):
            detected_anomalies.append({
                "entity_id": inv_id,
                "order_id": inv_to_order.get(inv_id),
                "issue_type": "DUPLICATE_INVOICE",
                "financial_impact_category": "Overbilling_And_Duplicate_Liability",
                "root_cause": "Concurrent batch billing re-run without invoice idempotency checks.",
                "detected_leakage_amount": round(float(inv_to_total.get(inv_id, 0.0)), 2),
                "assigned_actor": "analyst",
                "recommended_decision": "VOID_DUPLICATE_INVOICE"
            })

        non_dup_il = invoice_lines[~invoice_lines["invoice_id"].isin(dup_invoice_ids)]
        il_cum = non_dup_il.groupby("order_line_id", as_index=False).agg(
            total_invoiced_qty=("invoiced_qty", "sum"),
            unit_price=("unit_price", "first"),
            primary_invoice_id=("invoice_id", "first")
        )
        il_merged = il_cum.merge(shp_totals, on="order_line_id", how="left").fillna({"shipped_qty": 0})
        il_merged["days_since_ship"] = (self.cutoff_dt - pd.to_datetime(il_merged["last_ship_date"])).dt.days

        for _, row in il_merged[il_merged["total_invoiced_qty"] > il_merged["shipped_qty"]].iterrows():
            inv_id = row["primary_invoice_id"]
            overbilled_amt = round(float((row["total_invoiced_qty"] - row["shipped_qty"]) * row["unit_price"]), 2)
            detected_anomalies.append({
                "entity_id": inv_id,
                "order_id": inv_to_order.get(inv_id),
                "issue_type": "INVOICE_EXCEEDS_FULFILLED_QTY",
                "financial_impact_category": "Overbilling_And_Duplicate_Liability",
                "root_cause": "Warehouse packaging discrepancy or manual billing quantity over-entry.",
                "detected_leakage_amount": overbilled_amt,
                "assigned_actor": "analyst",
                "recommended_decision": "ISSUE_CREDIT_MEMO"
            })

        for _, row in il_merged[
            (il_merged["total_invoiced_qty"] < il_merged["shipped_qty"])
            & (il_merged["days_since_ship"] > 7)
        ].iterrows():
            inv_id = row["primary_invoice_id"]
            underbilled_amt = round(float((row["shipped_qty"] - row["total_invoiced_qty"]) * row["unit_price"]), 2)
            detected_anomalies.append({
                "entity_id": inv_id,
                "order_id": inv_to_order.get(inv_id),
                "issue_type": "UNDERBILLING_REVENUE_LEAKAGE",
                "financial_impact_category": "Direct_Revenue_Leakage",
                "root_cause": "Milestone billing schedule omission or unbilled supplemental shipment lines.",
                "detected_leakage_amount": underbilled_amt,
                "assigned_actor": "analyst",
                "recommended_decision": "ISSUE_SUPPLEMENTAL_INVOICE"
            })

        dup_alloc_payment_ids = set(
            payments[payments.duplicated(subset=["invoice_id", "amount", "allocation_ref"], keep="first")]["payment_id"]
        )
        overpaid_invoices = inv_pay_audit[
            (inv_pay_audit["unapplied_overpayment"] > 0.01)
            & (inv_pay_audit["latest_payment_id"].isin(dup_alloc_payment_ids))
        ]
        for _, row in overpaid_invoices.iterrows():
            detected_anomalies.append({
                "entity_id": row["latest_payment_id"],
                "order_id": row["order_id"],
                "issue_type": "PAYMENT_ALLOCATED_TWICE",
                "financial_impact_category": "Overbilling_And_Duplicate_Liability",
                "root_cause": "Duplicate bank remittance entry or multi-allocation clearing error.",
                "detected_leakage_amount": round(float(row["unapplied_overpayment"]), 2),
                "assigned_actor": "system administrator",
                "recommended_decision": "REVERSE_DUPLICATE_ALLOCATION"
            })

        open_disputed_invoices = set(disputes[disputes["dispute_status"] == "Open"]["invoice_id"])
        valid_open_ar_invs = inv_pay_audit[
            (~inv_pay_audit["invoice_id"].isin(dup_invoice_ids))
            & (~inv_pay_audit["invoice_id"].isin(open_disputed_invoices))
        ]
        unpaid_by_order = valid_open_ar_invs.groupby("order_id")["computed_net_balance"].sum().to_dict()

        for _, o in orders[orders["order_status"] == "Closed"].iterrows():
            unpaid_amt = round(float(unpaid_by_order.get(o["order_id"], 0.0)), 2)
            if unpaid_amt > 0.01:
                detected_anomalies.append({
                    "entity_id": o["order_id"],
                    "order_id": o["order_id"],
                    "issue_type": "ORDER_CLOSED_WITH_UNPAID_INVOICE",
                    "financial_impact_category": "Direct_Revenue_Leakage",
                    "root_cause": "Premature sales order closure before cash application and AR settlement.",
                    "detected_leakage_amount": unpaid_amt,
                    "assigned_actor": "marketing/sales operations",
                    "recommended_decision": "REOPEN_ORDER_AND_COLLECT_AR"
                })

        inv_balance_map = dict(zip(inv_pay_audit["invoice_id"], inv_pay_audit["computed_net_balance"]))
        for _, d in disputes.iterrows():
            if (
                d["dispute_status"] == "Open"
                and (not d["reflected_in_ar"])
                and inv_balance_map.get(d["invoice_id"], 0.0) >= d["disputed_amount"]
            ):
                detected_anomalies.append({
                    "entity_id": d["dispute_id"],
                    "order_id": inv_to_order.get(d["invoice_id"]),
                    "issue_type": "DISPUTE_NOT_REFLECTED_IN_AR",
                    "financial_impact_category": "AR_And_Compliance_Exposure",
                    "root_cause": "Support desk ticket settlement delay not synchronized to financial sub-ledger hold.",
                    "detected_leakage_amount": round(float(d["disputed_amount"]), 2),
                    "assigned_actor": "support agent",
                    "recommended_decision": "SYNC_DISPUTE_HOLD_TO_AR"
                })

        ol_shipped = order_lines.merge(shp_totals, on="order_line_id", how="left").fillna({"shipped_qty": 0})
        ol_shipped["days_since_last_ship"] = (self.cutoff_dt - pd.to_datetime(ol_shipped["last_ship_date"])).dt.days
        ol_shipped["shortfall_value"] = (
            (ol_shipped["ordered_qty"] - ol_shipped["shipped_qty"]) * ol_shipped["unit_price"]
        ).round(2)
        shortfall_lines = ol_shipped[
            (ol_shipped["shipped_qty"] < ol_shipped["ordered_qty"])
            & (ol_shipped["days_since_last_ship"] > 14)
        ]
        shortfall_by_order = shortfall_lines.groupby("order_id")["shortfall_value"].sum().round(2).to_dict()
        for order_id, shortfall_val in shortfall_by_order.items():
            detected_anomalies.append({
                "entity_id": order_id,
                "order_id": order_id,
                "issue_type": "PARTIAL_SHIPMENT",
                "financial_impact_category": "Direct_Revenue_Leakage",
                "root_cause": "Supply chain stockout or pending backorder fulfillment schedule.",
                "detected_leakage_amount": round(float(shortfall_val), 2),
                "assigned_actor": "Customer/prospect",
                "recommended_decision": "NOTIFY_BACKORDER_SCHEDULE"
            })

        for e_id in sorted(set(workflow_bypass_entities)):
            detected_anomalies.append({
                "entity_id": e_id,
                "order_id": e_id,
                "issue_type": "STATUS_EVENT_SKIPS_REQUIRED_STATE",
                "financial_impact_category": "AR_And_Compliance_Exposure",
                "root_cause": "Workflow engine bypass during manual exception override.",
                "detected_leakage_amount": round(float(ord_to_total.get(e_id, 0.0)), 2),
                "assigned_actor": "system administrator",
                "recommended_decision": "AUDIT_WORKFLOW_BYPASS"
            })

        detected_df = pd.DataFrame(detected_anomalies).drop_duplicates(subset=["entity_id", "issue_type"])

        trace_df = detected_df.merge(
            gt_df[["entity_id", "issue_type", "invoice_id", "expected_leakage_amount", "expected_decision"]],
            on=["entity_id", "issue_type"], how="left"
        )
        trace_df["leakage_amount_variance"] = (
            trace_df["detected_leakage_amount"] - trace_df["expected_leakage_amount"]
        ).round(2)
        trace_df["decision_matches_ground_truth"] = trace_df["recommended_decision"] == trace_df["expected_decision"]

        # Enforce exact expected column order for exceptions_and_decisions.csv
        expected_columns = [
            "entity_id", "order_id", "issue_type", "financial_impact_category",
            "detected_leakage_amount", "assigned_actor", "recommended_decision",
            "invoice_id", "root_cause", "expected_leakage_amount", "expected_decision",
            "leakage_amount_variance", "decision_matches_ground_truth"
        ]
        trace_df = trace_df[expected_columns]
        trace_df.to_csv(os.path.join(self.output_dir, "exceptions_and_decisions.csv"), index=False)

        shp_by_order = shipments.groupby("order_id", as_index=False)["ship_date"].max()
        ord_shp = orders.merge(shp_by_order, on="order_id", how="left")
        inv_by_order = invoices.groupby("order_id", as_index=False).agg(
            invoice_id=("invoice_id", "first"),
            invoice_date=("invoice_date", "min"),
            aging_days=("aging_days", "max"),
            balance_due=("balance_due", "sum")
        )
        ord_shp_inv = ord_shp.merge(inv_by_order, on="order_id", how="left")
        ord_shp_inv["fulfillment_delay_days"] = (pd.to_datetime(ord_shp_inv["ship_date"]) - pd.to_datetime(ord_shp_inv["order_date"])).dt.days
        delayed_df = ord_shp_inv[(ord_shp_inv["fulfillment_delay_days"] >= 10) | (ord_shp_inv["aging_days"] > 60)]
        delayed_df[["order_id", "invoice_id", "fulfillment_delay_days", "aging_days", "balance_due"]].to_csv(
            os.path.join(self.output_dir, "process_delays.csv"), index=False
        )

        eval_join = pd.merge(
            gt_df, detected_df,
            on=["entity_id", "order_id", "issue_type"],
            how="outer",
            indicator=True
        )
        tp_df = eval_join[
            (eval_join["_merge"] == "both")
            & (eval_join["expected_decision"] == eval_join["recommended_decision"])
            & ((eval_join["expected_leakage_amount"] - eval_join["detected_leakage_amount"]).abs() < 0.01)
        ]
        fp_df = eval_join[eval_join["_merge"] == "right_only"]
        fn_df = eval_join[eval_join["_merge"] == "left_only"]

        total_gt = len(gt_df)
        tp_count = len(tp_df)
        fp_count = len(fp_df)
        fn_count = len(fn_df)

        precision = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 1.0
        recall = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 1.0
        f1_score = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        per_class_metrics = {}
        for issue_t in sorted(gt_df["issue_type"].unique()):
            c_gt = gt_df[gt_df["issue_type"] == issue_t]
            c_det = detected_df[detected_df["issue_type"] == issue_t]
            c_joined = pd.merge(c_gt, c_det, on=["entity_id", "order_id", "issue_type"], how="inner")
            c_tp = len(c_joined[(c_joined["expected_leakage_amount"] - c_joined["detected_leakage_amount"]).abs() < 0.01])
            c_fp = len(c_det) - c_tp
            c_fn = len(c_gt) - c_tp
            c_prec = c_tp / len(c_det) if len(c_det) > 0 else 1.0
            c_rec = c_tp / len(c_gt) if len(c_gt) > 0 else 1.0
            c_f1 = (2 * c_prec * c_rec) / (c_prec + c_rec) if (c_prec + c_rec) > 0 else 0.0
            gt_sum = round(float(c_gt["expected_leakage_amount"].sum()), 2)
            det_sum = round(float(c_det["detected_leakage_amount"].sum()), 2)
            per_class_metrics[issue_t] = {
                "ground_truth": len(c_gt),
                "detected": len(c_det),
                "tp": c_tp,
                "fp": c_fp,
                "fn": c_fn,
                "precision": round(c_prec, 4),
                "recall": round(c_rec, 4),
                "f1_score": round(c_f1, 4),
                "expected_leakage_amount": gt_sum,
                "detected_leakage_amount": det_sum,
                "monetary_variance": round(det_sum - gt_sum, 2)
            }

        total_contracted_order_value = round(float(orders["order_total"].sum()), 2)
        total_invoiced_value = round(float(invoices["invoice_total"].sum()), 2)
        total_gt_leakage = round(float(gt_df["expected_leakage_amount"].sum()), 2)
        total_detected_leakage = round(float(detected_df["detected_leakage_amount"].sum()), 2)

        by_impact_bucket = (
            detected_df.groupby("financial_impact_category")["detected_leakage_amount"]
            .sum()
            .round(2)
            .to_dict()
        )
        direct_leakage_val = round(float(by_impact_bucket.get("Direct_Revenue_Leakage", 0.0)), 2)
        overbilling_liability_val = round(float(by_impact_bucket.get("Overbilling_And_Duplicate_Liability", 0.0)), 2)
        ar_compliance_exposure_val = round(float(by_impact_bucket.get("AR_And_Compliance_Exposure", 0.0)), 2)

        revenue_leakage_financial_summary = {
            "total_contracted_order_book_value": total_contracted_order_value,
            "total_gross_invoiced_value": total_invoiced_value,
            "ground_truth_total_financial_exposure": total_gt_leakage,
            "detected_total_financial_exposure": total_detected_leakage,
            "total_monetary_variance": round(total_detected_leakage - total_gt_leakage, 2),
            "exact_monetary_reconciliation_verified": abs(total_detected_leakage - total_gt_leakage) < 0.01,
            "direct_revenue_leakage_amount": direct_leakage_val,
            "direct_revenue_leakage_pct_of_order_book": round((direct_leakage_val / total_contracted_order_value) * 100, 4),
            "overbilling_and_duplicate_liability_amount": overbilling_liability_val,
            "ar_and_workflow_compliance_exposure_amount": ar_compliance_exposure_val,
            "breakdown_by_issue_type": {
                k: v["detected_leakage_amount"] for k, v in per_class_metrics.items()
            }
        }

        hn_cohorts = {
            "legitimate_split_shipments": {f"SO-2026-{i:06d}" for i in range(256, 281)},
            "same_day_50_50_split_invoices": {f"SO-2026-{i:06d}" for i in range(281, 306)},
            "legitimate_split_payments": {f"SO-2026-{i:06d}" for i in range(306, 326)},
            "active_within_sla_backorders": {f"SO-2026-{i:06d}" for i in range(326, 346)},
            "resolved_historical_disputes": {f"SO-2026-{i:06d}" for i in range(346, 366)}
        }
        hard_negative_orders = set().union(*hn_cohorts.values())
        hn_false_alarms = detected_df[detected_df["order_id"].isin(hard_negative_orders)]

        false_positive_control_audit = {
            cohort_name: {
                "cases_tested": len(cohort_ids),
                "false_positives_triggered": int(len(detected_df[detected_df["order_id"].isin(cohort_ids)]))
            }
            for cohort_name, cohort_ids in hn_cohorts.items()
        }

        metrics = {
            "total_ground_truth_anomalies": total_gt,
            "total_detected_anomalies": len(detected_df),
            "true_positives": tp_count,
            "false_positives": fp_count,
            "false_negatives": fn_count,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1_score, 4),
            "revenue_leakage_financial_summary": revenue_leakage_financial_summary,
            "hard_negative_edge_cases_tested": len(hard_negative_orders),
            "hard_negative_false_positives": len(hn_false_alarms),
            "false_positive_control_audit": false_positive_control_audit,
            "per_class_evaluation": per_class_metrics,
            "process_delays_flagged": len(delayed_df),
            "reproducibility_verified": reproducible,
            "step8_schema_validation": schema_checks
        }

        with open(os.path.join(self.output_dir, "validation_summary.json"), "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        print("[+] Financial Revenue Leakage Quantification & 11-Table Reconciliation Completed!")
        print(f"    - Reproducibility Verified (Step 10): {reproducible}")
        print(f"    - All 11 Primary Keys Unique: {schema_checks['primary_key_uniqueness']}")
        print(f"    - All 22 Foreign Key & Transitive Relationships Valid: {schema_checks['foreign_key_integrity']}")
        print(f"    - Direct Revenue Leakage Quantified: {direct_leakage_val:,.2f}")
        print(f"    - Overbilling & Duplicate Liability Quantified: {overbilling_liability_val:,.2f}")
        print(f"    - AR & Compliance Exposure Quantified: {ar_compliance_exposure_val:,.2f}")
        print(f"    - Total Financial Exposure Reconciled (0.00 Variance): {revenue_leakage_financial_summary['exact_monetary_reconciliation_verified']}")
        print(f"    - Ground Truth Anomalies: {total_gt} | Detected: {len(detected_df)}")
        print(f"    - Precision: {precision:.4f} | Recall: {recall:.4f} | F1-Score: {f1_score:.4f}")

        return metrics

if __name__ == "__main__":
    validator = O2CValidatorAndDetector()
    validator.run_pipeline()