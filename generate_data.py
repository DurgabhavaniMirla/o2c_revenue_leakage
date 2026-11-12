import os
import json
import random
from datetime import datetime, timedelta
import pandas as pd

class O2CSyntheticGenerator:
    def __init__(self, seed: int = 20261022, scale: float = 1.0, cutoff_date: str = "2026-10-31"):
        self.seed = seed
        self.scale = scale
        self.cutoff_dt = datetime.strptime(cutoff_date, "%Y-%m-%d")
        self.rng = random.Random(seed)
        self.ground_truth = []

    def _fmt_id(self, prefix: str, idx: int) -> str:
        return f"{prefix}-2026-{idx:06d}"

    def _add_days(self, dt_str: str, days: int) -> str:
        dt = datetime.strptime(dt_str, "%Y-%m-%d") + timedelta(days=days)
        return dt.strftime("%Y-%m-%d")

    def generate_all(self, data_dir: str = "data", output_dir: str = "output"):
        self.rng = random.Random(self.seed)
        self.ground_truth = []

        print(f"[*] Generating dataset with Seed: {self.seed}, Scale: {self.scale}...")
        n_orders = max(365, int(7000 * self.scale))
        n_quotes = max(n_orders, int(10000 * self.scale))
        n_accounts = max(50, int(1500 * self.scale))
        target_invoices = max(n_orders + 65, int(8000 * self.scale))
        target_events = max(1500, int(15000 * self.scale))

        extra_milestone_orders_needed = max(0, target_invoices - (n_orders + 40 + 25))
        milestone_split_end_idx = 365 + extra_milestone_orders_needed
        audited_order_event_limit = max(1000, int(1000 * self.scale))

        accounts = []
        quotes, quote_lines = [], []
        orders, order_lines = [], []
        shipments = []
        invoices, invoice_lines = [], []
        payments, disputes, status_events = [], [], []

        segments = ["Enterprise", "Mid-Market", "SMB"]
        products = [f"PRD-{i:03d}" for i in range(1, 51)]
        product_prices = {p: round(self.rng.uniform(500.0, 25000.0), 2) for p in products}

        base_start = datetime(2026, 1, 1)
        for i in range(1, n_accounts + 1):
            c_date = (base_start + timedelta(days=self.rng.randint(0, 45))).strftime("%Y-%m-%d")
            seg = self.rng.choice(segments)
            limit = 5000000.0 if seg == "Enterprise" else (1000000.0 if seg == "Mid-Market" else 250000.0)
            accounts.append({
                "account_id": self._fmt_id("ACC", i),
                "account_name": f"GlobalCorp_{i:04d}_Ltd",
                "segment": seg,
                "credit_limit": round(limit, 2),
                "ar_balance": 0.0,
                "created_date": c_date
            })

        evt_counter = 1
        ql_counter = 1

        def log_event(entity_type, entity_id, from_st, to_st, dt_str, hour_offset, actor):
            nonlocal evt_counter
            ts = f"{dt_str} {hour_offset:02d}:{self.rng.randint(10, 59):02d}:00"
            status_events.append({
                "event_id": self._fmt_id("EVT", evt_counter),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "from_state": from_st,
                "to_state": to_st,
                "event_timestamp": ts,
                "actor": actor
            })
            evt_counter += 1

        accepted_indices = set(self.rng.sample(range(1, n_quotes + 1), n_orders))
        accepted_rank = 0
        for i in range(1, n_quotes + 1):
            acc = self.rng.choice(accounts)
            q_id = self._fmt_id("QTE", i)
            q_date = self._add_days(acc["created_date"], self.rng.randint(1, 120))
            v_until = self._add_days(q_date, 30)

            is_accepted = i in accepted_indices
            if is_accepted:
                accepted_rank += 1

            num_lines = 1 if (is_accepted and accepted_rank <= 365) else self.rng.randint(1, 3)
            q_total = 0.0
            for _ in range(num_lines):
                prd = self.rng.choice(products)
                qty = self.rng.randint(5, 50) * 2
                price = product_prices[prd]
                l_total = round(qty * price, 2)
                q_total = round(q_total + l_total, 2)
                quote_lines.append({
                    "quote_line_id": self._fmt_id("QLN", ql_counter),
                    "quote_id": q_id,
                    "product_code": prd,
                    "quantity": qty,
                    "unit_price": price,
                    "line_total": l_total
                })
                ql_counter += 1

            q_status = "Accepted" if is_accepted else self.rng.choice(["Sent", "Rejected", "Expired"])
            quotes.append({
                "quote_id": q_id,
                "account_id": acc["account_id"],
                "quote_date": q_date,
                "valid_until": v_until,
                "quote_status": q_status,
                "quote_total": q_total
            })
            if is_accepted:
                log_event("Quote", q_id, "NULL", "Draft", q_date, 8, "Sales_Rep")
                log_event("Quote", q_id, "Draft", q_status, q_date, 11, "Sales_Ops")

        ql_by_quote = {}
        for ql in quote_lines:
            ql_by_quote.setdefault(ql["quote_id"], []).append(ql)

        ol_counter, shp_counter, shpl_counter, inv_counter, il_counter, pay_counter, dsp_counter = 1, 1, 1, 1, 1, 1, 1
        accepted_quotes = [q for q in quotes if q["quote_status"] == "Accepted"]

        expected_action_map = {
            "INVOICE_EXCEEDS_FULFILLED_QTY": "ISSUE_CREDIT_MEMO",
            "UNDERBILLING_REVENUE_LEAKAGE": "ISSUE_SUPPLEMENTAL_INVOICE",
            "PAYMENT_ALLOCATED_TWICE": "REVERSE_DUPLICATE_ALLOCATION",
            "ORDER_CLOSED_WITH_UNPAID_INVOICE": "REOPEN_ORDER_AND_COLLECT_AR",
            "DISPUTE_NOT_REFLECTED_IN_AR": "SYNC_DISPUTE_HOLD_TO_AR",
            "DUPLICATE_INVOICE": "VOID_DUPLICATE_INVOICE",
            "PARTIAL_SHIPMENT": "NOTIFY_BACKORDER_SCHEDULE",
            "STATUS_EVENT_SKIPS_REQUIRED_STATE": "AUDIT_WORKFLOW_BYPASS"
        }

        root_cause_map = {
            "INVOICE_EXCEEDS_FULFILLED_QTY": "Warehouse packaging discrepancy or manual billing quantity over-entry.",
            "UNDERBILLING_REVENUE_LEAKAGE": "Milestone billing schedule omission or unbilled supplemental shipment lines.",
            "PAYMENT_ALLOCATED_TWICE": "Duplicate bank remittance entry or multi-allocation clearing error.",
            "ORDER_CLOSED_WITH_UNPAID_INVOICE": "Premature sales order closure before cash application and AR settlement.",
            "DISPUTE_NOT_REFLECTED_IN_AR": "Support desk ticket settlement delay not synchronized to financial sub-ledger hold.",
            "DUPLICATE_INVOICE": "Concurrent batch billing re-run without invoice idempotency checks.",
            "PARTIAL_SHIPMENT": "Supply chain stockout or pending backorder fulfillment schedule.",
            "STATUS_EVENT_SKIPS_REQUIRED_STATE": "Workflow engine bypass during manual exception override."
        }

        impact_category_map = {
            "UNDERBILLING_REVENUE_LEAKAGE": "Direct_Revenue_Leakage",
            "ORDER_CLOSED_WITH_UNPAID_INVOICE": "Direct_Revenue_Leakage",
            "PARTIAL_SHIPMENT": "Direct_Revenue_Leakage",
            "INVOICE_EXCEEDS_FULFILLED_QTY": "Overbilling_And_Duplicate_Liability",
            "DUPLICATE_INVOICE": "Overbilling_And_Duplicate_Liability",
            "PAYMENT_ALLOCATED_TWICE": "Overbilling_And_Duplicate_Liability",
            "DISPUTE_NOT_REFLECTED_IN_AR": "AR_And_Compliance_Exposure",
            "STATUS_EVENT_SKIPS_REQUIRED_STATE": "AR_And_Compliance_Exposure"
        }

        for idx, q in enumerate(accepted_quotes, start=1):
            so_id = self._fmt_id("SO", idx)

            anomaly_type = None
            hard_negative_type = None
            if idx <= 25: anomaly_type = "INVOICE_EXCEEDS_FULFILLED_QTY"
            elif 25 < idx <= 50: anomaly_type = "PAYMENT_ALLOCATED_TWICE"
            elif 50 < idx <= 75: anomaly_type = "ORDER_CLOSED_WITH_UNPAID_INVOICE"
            elif 75 < idx <= 100: anomaly_type = "STATUS_EVENT_SKIPS_REQUIRED_STATE"
            elif 100 < idx <= 125: anomaly_type = "DISPUTE_NOT_REFLECTED_IN_AR"
            elif 125 < idx <= 165: anomaly_type = "UNDERBILLING_REVENUE_LEAKAGE"
            elif 165 < idx <= 205: anomaly_type = "DUPLICATE_INVOICE"
            elif 205 < idx <= 255: anomaly_type = "PARTIAL_SHIPMENT"
            elif 255 < idx <= 280: hard_negative_type = "LEGITIMATE_SPLIT_SHIPMENT"
            elif 280 < idx <= 305: hard_negative_type = "LEGITIMATE_SAME_DAY_50_50_INVOICE"
            elif 305 < idx <= 325: hard_negative_type = "LEGITIMATE_SPLIT_PAYMENT"
            elif 325 < idx <= 345: hard_negative_type = "ACTIVE_WITHIN_SLA_BACKORDER"
            elif 345 < idx <= 365: hard_negative_type = "RESOLVED_DISPUTE_CLEAN"
            elif 365 < idx <= milestone_split_end_idx: hard_negative_type = "PAID_MILESTONE_INSTALLMENT_BILLING"

            if hard_negative_type == "ACTIVE_WITHIN_SLA_BACKORDER":
                q["quote_date"] = "2026-10-25"
                q["valid_until"] = "2026-11-24"
                o_date = "2026-10-27"
                s_date = "2026-10-29"
                inv_date = "2026-10-30"
                due_date = "2026-11-29"
            else:
                o_date = self._add_days(q["quote_date"], self.rng.randint(1, 10))
                s_date = self._add_days(o_date, self.rng.randint(2, 12))
                inv_date = self._add_days(s_date, self.rng.randint(3, 7))
                due_date = self._add_days(inv_date, 30)

            q_lines = ql_by_quote[q["quote_id"]]
            o_total = 0.0
            current_order_lines = []

            if hard_negative_type == "LEGITIMATE_SPLIT_SHIPMENT":
                shp_id_1 = self._fmt_id("SHP", shp_counter)
                shp_counter += 1
                shp_id_2 = self._fmt_id("SHP", shp_counter)
                shp_counter += 1
            else:
                primary_shp_id = self._fmt_id("SHP", shp_counter)
                shp_counter += 1

            for ql in q_lines:
                ord_qty = ql["quantity"]
                is_short_ship = anomaly_type == "PARTIAL_SHIPMENT" or hard_negative_type == "ACTIVE_WITHIN_SLA_BACKORDER"
                ful_qty = max(2, int(ord_qty * 0.6)) if is_short_ship else ord_qty
                l_tot = round(ord_qty * ql["unit_price"], 2)
                o_total = round(o_total + l_tot, 2)
                ol_id = self._fmt_id("OLN", ol_counter)
                ol_counter += 1

                ol_rec = {
                    "order_line_id": ol_id,
                    "order_id": so_id,
                    "product_code": ql["product_code"],
                    "ordered_qty": ord_qty,
                    "fulfilled_qty": ful_qty,
                    "unit_price": ql["unit_price"],
                    "line_total": l_tot
                }
                order_lines.append(ol_rec)
                current_order_lines.append(ol_rec)

                if hard_negative_type == "LEGITIMATE_SPLIT_SHIPMENT":
                    shp1_qty = int(ord_qty * 0.6)
                    shp2_qty = ord_qty - shp1_qty
                    shipments.append({
                        "shipment_line_id": self._fmt_id("SHPL", shpl_counter),
                        "shipment_id": shp_id_1,
                        "order_id": so_id,
                        "order_line_id": ol_id,
                        "shipped_qty": shp1_qty,
                        "ship_date": s_date,
                        "shipment_status": "Partial"
                    })
                    log_event("Shipment", shp_id_1, "NULL", "Partial", s_date, 11, "Warehouse_Ops")
                    shpl_counter += 1
                    shipments.append({
                        "shipment_line_id": self._fmt_id("SHPL", shpl_counter),
                        "shipment_id": shp_id_2,
                        "order_id": so_id,
                        "order_line_id": ol_id,
                        "shipped_qty": shp2_qty,
                        "ship_date": self._add_days(s_date, 2),
                        "shipment_status": "Delivered"
                    })
                    log_event("Shipment", shp_id_2, "Partial", "Delivered", self._add_days(s_date, 2), 11, "Warehouse_Ops")
                    shpl_counter += 1
                else:
                    st_val = "Partial" if ful_qty < ord_qty else "Delivered"
                    shipments.append({
                        "shipment_line_id": self._fmt_id("SHPL", shpl_counter),
                        "shipment_id": primary_shp_id,
                        "order_id": so_id,
                        "order_line_id": ol_id,
                        "shipped_qty": ful_qty,
                        "ship_date": s_date,
                        "shipment_status": st_val
                    })
                    log_event("Shipment", primary_shp_id, "NULL", st_val, s_date, 11, "Warehouse_Ops")
                    shpl_counter += 1

            if hard_negative_type == "LEGITIMATE_SAME_DAY_50_50_INVOICE":
                ol_rec = current_order_lines[0]
                half_qty = ol_rec["fulfilled_qty"] // 2

                for m_idx in (1, 2):
                    m_inv_id = self._fmt_id("INV", inv_counter)
                    inv_counter += 1
                    m_tot = round(half_qty * ol_rec["unit_price"], 2)
                    invoice_lines.append({
                        "invoice_line_id": self._fmt_id("ILN", il_counter),
                        "invoice_id": m_inv_id,
                        "order_line_id": ol_rec["order_line_id"],
                        "invoiced_qty": half_qty,
                        "unit_price": ol_rec["unit_price"],
                        "line_total": m_tot
                    })
                    il_counter += 1

                    if m_idx == 1:
                        pay_id_m1 = self._fmt_id("PAY", pay_counter)
                        payments.append({
                            "payment_id": pay_id_m1,
                            "invoice_id": m_inv_id,
                            "account_id": q["account_id"],
                            "payment_date": self._add_days(inv_date, 5),
                            "amount": m_tot,
                            "allocation_ref": f"ALLOC-{idx:06d}-M1",
                            "payment_status": "Allocated"
                        })
                        log_event("Payment", pay_id_m1, "NULL", "Allocated", self._add_days(inv_date, 5), 13, "Finance_Bot")
                        pay_counter += 1
                        invoices.append({
                            "invoice_id": m_inv_id, "order_id": so_id, "account_id": q["account_id"],
                            "invoice_date": inv_date, "due_date": due_date, "invoice_total": m_tot,
                            "paid_amount": m_tot, "balance_due": 0.0, "aging_days": 0, "invoice_status": "Paid"
                        })
                        log_event("Invoice", m_inv_id, "NULL", "Paid", inv_date, 13, "Finance_Bot")
                    else:
                        invoices.append({
                            "invoice_id": m_inv_id, "order_id": so_id, "account_id": q["account_id"],
                            "invoice_date": inv_date, "due_date": due_date, "invoice_total": m_tot,
                            "paid_amount": 0.0, "balance_due": m_tot, "aging_days": 0, "invoice_status": "Issued"
                        })
                        log_event("Invoice", m_inv_id, "NULL", "Issued", inv_date, 13, "Finance_Bot")

                orders.append({
                    "order_id": so_id, "quote_id": q["quote_id"], "account_id": q["account_id"],
                    "order_date": o_date, "order_status": "Invoiced", "order_total": o_total
                })
                log_event("SalesOrder", so_id, "NULL", "Created", o_date, 10, "Sales_Ops")
                log_event("SalesOrder", so_id, "Created", "Fulfilled", s_date, 12, "Sys_Admin")
                log_event("SalesOrder", so_id, "Fulfilled", "Invoiced", inv_date, 15, "Finance_Bot")
                continue

            if hard_negative_type == "PAID_MILESTONE_INSTALLMENT_BILLING":
                last_pay_date = inv_date
                for m_idx in (1, 2):
                    m_inv_id = self._fmt_id("INV", inv_counter)
                    inv_counter += 1
                    m_inv_date = inv_date if m_idx == 1 else self._add_days(inv_date, 4)
                    m_due_date = self._add_days(m_inv_date, 30)
                    m_pay_date = self._add_days(m_inv_date, 5)
                    last_pay_date = m_pay_date
                    m_inv_total = 0.0

                    for ol_rec in current_order_lines:
                        half_q = ol_rec["fulfilled_qty"] // 2
                        rem_q = ol_rec["fulfilled_qty"] - half_q
                        m_qty = half_q if m_idx == 1 else rem_q
                        m_line_tot = round(m_qty * ol_rec["unit_price"], 2)
                        m_inv_total = round(m_inv_total + m_line_tot, 2)
                        invoice_lines.append({
                            "invoice_line_id": self._fmt_id("ILN", il_counter),
                            "invoice_id": m_inv_id,
                            "order_line_id": ol_rec["order_line_id"],
                            "invoiced_qty": m_qty,
                            "unit_price": ol_rec["unit_price"],
                            "line_total": m_line_tot
                        })
                        il_counter += 1

                    invoices.append({
                        "invoice_id": m_inv_id, "order_id": so_id, "account_id": q["account_id"],
                        "invoice_date": m_inv_date, "due_date": m_due_date, "invoice_total": m_inv_total,
                        "paid_amount": m_inv_total, "balance_due": 0.0, "aging_days": 0, "invoice_status": "Paid"
                    })
                    log_event("Invoice", m_inv_id, "NULL", "Paid", m_inv_date, 13, "Finance_Bot")

                    pay_id_inst = self._fmt_id("PAY", pay_counter)
                    payments.append({
                        "payment_id": pay_id_inst,
                        "invoice_id": m_inv_id,
                        "account_id": q["account_id"],
                        "payment_date": m_pay_date,
                        "amount": m_inv_total,
                        "allocation_ref": f"ALLOC-{idx:06d}-INST{m_idx}",
                        "payment_status": "Allocated"
                    })
                    log_event("Payment", pay_id_inst, "NULL", "Allocated", m_pay_date, 13, "Finance_Bot")
                    pay_counter += 1

                orders.append({
                    "order_id": so_id, "quote_id": q["quote_id"], "account_id": q["account_id"],
                    "order_date": o_date, "order_status": "Closed", "order_total": o_total
                })
                if idx <= audited_order_event_limit:
                    log_event("SalesOrder", so_id, "NULL", "Created", o_date, 10, "Sales_Ops")
                    log_event("SalesOrder", so_id, "Created", "Fulfilled", s_date, 12, "Warehouse_Ops")
                    log_event("SalesOrder", so_id, "Fulfilled", "Invoiced", inv_date, 14, "Finance_Bot")
                    log_event("SalesOrder", so_id, "Invoiced", "Closed", last_pay_date, 17, "Finance_Bot")
                continue

            inv_id = self._fmt_id("INV", inv_counter)
            inv_counter += 1
            inv_total = 0.0

            for ol_rec in current_order_lines:
                shipped_q = ol_rec["fulfilled_qty"]
                inv_qty = shipped_q + 10 if anomaly_type == "INVOICE_EXCEEDS_FULFILLED_QTY" else (max(1, shipped_q - 5) if anomaly_type == "UNDERBILLING_REVENUE_LEAKAGE" else shipped_q)
                il_tot = round(inv_qty * ol_rec["unit_price"], 2)
                inv_total = round(inv_total + il_tot, 2)
                invoice_lines.append({
                    "invoice_line_id": self._fmt_id("ILN", il_counter),
                    "invoice_id": inv_id,
                    "order_line_id": ol_rec["order_line_id"],
                    "invoiced_qty": inv_qty,
                    "unit_price": ol_rec["unit_price"],
                    "line_total": il_tot
                })
                il_counter += 1

            paid_amt = 0.0
            pay_date = self._add_days(inv_date, 1 if hard_negative_type == "ACTIVE_WITHIN_SLA_BACKORDER" else self.rng.randint(5, 25))
            alloc_ref = f"ALLOC-{idx:06d}"

            if anomaly_type in ("ORDER_CLOSED_WITH_UNPAID_INVOICE", "DISPUTE_NOT_REFLECTED_IN_AR"):
                paid_amt = 0.0
            elif anomaly_type == "PAYMENT_ALLOCATED_TWICE":
                paid_amt = inv_total
                for p_idx_sub in range(2):
                    pay_id_dup = self._fmt_id("PAY", pay_counter)
                    payments.append({
                        "payment_id": pay_id_dup,
                        "invoice_id": inv_id,
                        "account_id": q["account_id"],
                        "payment_date": pay_date,
                        "amount": inv_total,
                        "allocation_ref": alloc_ref,
                        "payment_status": "Duplicate_Allocation"
                    })
                    log_event("Payment", pay_id_dup, "NULL", "Duplicate_Allocation", pay_date, 13, "Finance_Bot")
                    pay_counter += 1
            elif hard_negative_type == "LEGITIMATE_SPLIT_PAYMENT":
                p1 = round(inv_total * 0.6, 2)
                p2 = round(inv_total - p1, 2)
                paid_amt = inv_total
                pay_id_p1 = self._fmt_id("PAY", pay_counter)
                payments.append({
                    "payment_id": pay_id_p1,
                    "invoice_id": inv_id,
                    "account_id": q["account_id"],
                    "payment_date": pay_date,
                    "amount": p1,
                    "allocation_ref": f"{alloc_ref}-P1",
                    "payment_status": "Allocated"
                })
                log_event("Payment", pay_id_p1, "NULL", "Allocated", pay_date, 13, "Finance_Bot")
                pay_counter += 1

                pay_id_p2 = self._fmt_id("PAY", pay_counter)
                payments.append({
                    "payment_id": pay_id_p2,
                    "invoice_id": inv_id,
                    "account_id": q["account_id"],
                    "payment_date": self._add_days(pay_date, 3),
                    "amount": p2,
                    "allocation_ref": f"{alloc_ref}-P2",
                    "payment_status": "Allocated"
                })
                log_event("Payment", pay_id_p2, "NULL", "Allocated", self._add_days(pay_date, 3), 13, "Finance_Bot")
                pay_counter += 1
            else:
                paid_amt = inv_total
                pay_id_std = self._fmt_id("PAY", pay_counter)
                payments.append({
                    "payment_id": pay_id_std,
                    "invoice_id": inv_id,
                    "account_id": q["account_id"],
                    "payment_date": pay_date,
                    "amount": paid_amt,
                    "allocation_ref": alloc_ref,
                    "payment_status": "Allocated"
                })
                log_event("Payment", pay_id_std, "NULL", "Allocated", pay_date, 13, "Finance_Bot")
                pay_counter += 1

            balance_due = round(inv_total - paid_amt, 2)
            due_dt = datetime.strptime(due_date, "%Y-%m-%d")
            aging_days = max(0, (self.cutoff_dt - due_dt).days) if balance_due > 0 else 0

            if anomaly_type == "DISPUTE_NOT_REFLECTED_IN_AR":
                dsp_id_open = self._fmt_id("DSP", dsp_counter)
                disputes.append({
                    "dispute_id": dsp_id_open,
                    "invoice_id": inv_id,
                    "account_id": q["account_id"],
                    "dispute_date": self._add_days(inv_date, 4),
                    "disputed_amount": inv_total,
                    "reason_code": "Pricing_Error",
                    "reflected_in_ar": False,
                    "dispute_status": "Open"
                })
                log_event("Dispute", dsp_id_open, "NULL", "Open", self._add_days(inv_date, 4), 14, "Support_Agent")
                dsp_counter += 1
                inv_status = "Disputed"
            elif hard_negative_type == "RESOLVED_DISPUTE_CLEAN":
                dsp_id_res = self._fmt_id("DSP", dsp_counter)
                disputes.append({
                    "dispute_id": dsp_id_res,
                    "invoice_id": inv_id,
                    "account_id": q["account_id"],
                    "dispute_date": self._add_days(inv_date, 2),
                    "disputed_amount": round(inv_total * 0.2, 2),
                    "reason_code": "Tax_Adjustment_Settled",
                    "reflected_in_ar": False,
                    "dispute_status": "Resolved"
                })
                log_event("Dispute", dsp_id_res, "NULL", "Resolved", self._add_days(inv_date, 2), 14, "Support_Agent")
                dsp_counter += 1
                inv_status = "Paid"
            else:
                inv_status = "Paid" if balance_due == 0.0 else ("Overdue" if aging_days > 0 else "Issued")

            invoices.append({
                "invoice_id": inv_id,
                "order_id": so_id,
                "account_id": q["account_id"],
                "invoice_date": inv_date,
                "due_date": due_date,
                "invoice_total": inv_total,
                "paid_amount": paid_amt,
                "balance_due": balance_due,
                "aging_days": aging_days,
                "invoice_status": inv_status
            })
            log_event("Invoice", inv_id, "NULL", inv_status, inv_date, 12, "Finance_Bot")

            if anomaly_type == "ORDER_CLOSED_WITH_UNPAID_INVOICE":
                o_status = "Closed"
            elif anomaly_type == "PARTIAL_SHIPMENT" or hard_negative_type == "ACTIVE_WITHIN_SLA_BACKORDER":
                o_status = "Partially_Fulfilled"
            elif balance_due == 0.0:
                o_status = "Closed"
            else:
                o_status = "Invoiced"

            orders.append({
                "order_id": so_id,
                "quote_id": q["quote_id"],
                "account_id": q["account_id"],
                "order_date": o_date,
                "order_status": o_status,
                "order_total": o_total
            })

            if anomaly_type == "STATUS_EVENT_SKIPS_REQUIRED_STATE":
                log_event("SalesOrder", so_id, "NULL", "Created", o_date, 10, "Sales_Ops")
                log_event("SalesOrder", so_id, "Created", "Invoiced", inv_date, 14, "Sys_Admin")
                log_event("SalesOrder", so_id, "Invoiced", "Closed", pay_date, 16, "Finance_Bot")
            elif idx <= audited_order_event_limit:
                log_event("SalesOrder", so_id, "NULL", "Created", o_date, 10, "Sales_Ops")
                if o_status == "Partially_Fulfilled":
                    log_event("SalesOrder", so_id, "Created", "Partially_Fulfilled", s_date, 12, "Warehouse_Ops")
                elif o_status == "Invoiced":
                    log_event("SalesOrder", so_id, "Created", "Fulfilled", s_date, 12, "Warehouse_Ops")
                    log_event("SalesOrder", so_id, "Fulfilled", "Invoiced", inv_date, 14, "Finance_Bot")
                else:
                    log_event("SalesOrder", so_id, "Created", "Fulfilled", s_date, 12, "Warehouse_Ops")
                    log_event("SalesOrder", so_id, "Fulfilled", "Invoiced", inv_date, 14, "Finance_Bot")
                    close_dt = inv_date if anomaly_type == "ORDER_CLOSED_WITH_UNPAID_INVOICE" else pay_date
                    log_event("SalesOrder", so_id, "Invoiced", "Closed", close_dt, 17, "Finance_Bot")

            if anomaly_type == "DUPLICATE_INVOICE":
                dup_inv_id = self._fmt_id("INV", inv_counter)
                inv_counter += 1
                invoices.append({
                    "invoice_id": dup_inv_id,
                    "order_id": so_id,
                    "account_id": q["account_id"],
                    "invoice_date": inv_date,
                    "due_date": due_date,
                    "invoice_total": inv_total,
                    "paid_amount": 0.0,
                    "balance_due": inv_total,
                    "aging_days": aging_days,
                    "invoice_status": "Issued"
                })
                log_event("Invoice", dup_inv_id, "NULL", "Issued", inv_date, 12, "Finance_Bot")
                for ol_rec in current_order_lines:
                    invoice_lines.append({
                        "invoice_line_id": self._fmt_id("ILN", il_counter),
                        "invoice_id": dup_inv_id,
                        "order_line_id": ol_rec["order_line_id"],
                        "invoiced_qty": ol_rec["fulfilled_qty"],
                        "unit_price": ol_rec["unit_price"],
                        "line_total": round(ol_rec["fulfilled_qty"] * ol_rec["unit_price"], 2)
                    })
                    il_counter += 1
                self.ground_truth.append({
                    "anomaly_id": f"GT-{len(self.ground_truth)+1:05d}",
                    "entity_id": dup_inv_id,
                    "order_id": so_id,
                    "invoice_id": dup_inv_id,
                    "issue_type": "DUPLICATE_INVOICE",
                    "financial_impact_category": impact_category_map["DUPLICATE_INVOICE"],
                    "root_cause": root_cause_map["DUPLICATE_INVOICE"],
                    "expected_leakage_amount": round(inv_total, 2),
                    "expected_decision": expected_action_map["DUPLICATE_INVOICE"]
                })
            elif anomaly_type:
                ol_0 = current_order_lines[0]
                fulfilled_val = round(ol_0["fulfilled_qty"] * ol_0["unit_price"], 2)
                if anomaly_type == "INVOICE_EXCEEDS_FULFILLED_QTY":
                    target_id = inv_id
                    exp_leakage = round(inv_total - fulfilled_val, 2)
                elif anomaly_type == "UNDERBILLING_REVENUE_LEAKAGE":
                    target_id = inv_id
                    exp_leakage = round(fulfilled_val - inv_total, 2)
                elif anomaly_type == "PAYMENT_ALLOCATED_TWICE":
                    target_id = payments[-1]["payment_id"]
                    exp_leakage = round(inv_total, 2)
                elif anomaly_type == "ORDER_CLOSED_WITH_UNPAID_INVOICE":
                    target_id = so_id
                    exp_leakage = round(balance_due, 2)
                elif anomaly_type == "DISPUTE_NOT_REFLECTED_IN_AR":
                    target_id = disputes[-1]["dispute_id"]
                    exp_leakage = round(inv_total, 2)
                elif anomaly_type == "PARTIAL_SHIPMENT":
                    target_id = so_id
                    exp_leakage = round((ol_0["ordered_qty"] - ol_0["fulfilled_qty"]) * ol_0["unit_price"], 2)
                elif anomaly_type == "STATUS_EVENT_SKIPS_REQUIRED_STATE":
                    target_id = so_id
                    exp_leakage = round(o_total, 2)
                else:
                    target_id = so_id
                    exp_leakage = 0.0

                self.ground_truth.append({
                    "anomaly_id": f"GT-{len(self.ground_truth)+1:05d}",
                    "entity_id": target_id,
                    "order_id": so_id,
                    "invoice_id": inv_id,
                    "issue_type": anomaly_type,
                    "financial_impact_category": impact_category_map[anomaly_type],
                    "root_cause": root_cause_map[anomaly_type],
                    "expected_leakage_amount": exp_leakage,
                    "expected_decision": expected_action_map[anomaly_type]
                })

        q_idx = 0
        while len(status_events) < target_events and q_idx < len(quotes):
            q = quotes[q_idx]
            q_idx += 1
            rem = target_events - len(status_events)
            if rem >= 2:
                log_event("Quote", q["quote_id"], "NULL", "Draft", q["quote_date"], 8, "Sales_Rep")
                log_event("Quote", q["quote_id"], "Draft", q["quote_status"], q["quote_date"], 11, "Sales_Ops")
            else:
                log_event("Quote", q["quote_id"], "NULL", q["quote_status"], q["quote_date"], 9, "Sales_Ops")

        ar_by_acc = {}
        for inv in invoices:
            ar_by_acc[inv["account_id"]] = round(ar_by_acc.get(inv["account_id"], 0.0) + inv["balance_due"], 2)
        for acc in accounts:
            acc["ar_balance"] = round(ar_by_acc.get(acc["account_id"], 0.0), 2)

        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        tables = {
            "accounts": pd.DataFrame(accounts),
            "quotes": pd.DataFrame(quotes),
            "quote_lines": pd.DataFrame(quote_lines),
            "sales_orders": pd.DataFrame(orders),
            "order_lines": pd.DataFrame(order_lines),
            "shipments": pd.DataFrame(shipments),
            "invoices": pd.DataFrame(invoices),
            "invoice_lines": pd.DataFrame(invoice_lines),
            "payments": pd.DataFrame(payments),
            "disputes": pd.DataFrame(disputes),
            "status_events": pd.DataFrame(status_events)
        }

        for name, df in tables.items():
            df.to_csv(os.path.join(data_dir, f"{name}.csv"), index=False)
            df.to_json(os.path.join(data_dir, f"{name}.json"), orient="records", indent=2)

        pd.DataFrame(self.ground_truth).to_csv(os.path.join(output_dir, "ground_truth.csv"), index=False)
        pd.DataFrame(self.ground_truth).to_json(os.path.join(output_dir, "ground_truth.json"), orient="records", indent=2)

        sql_path = os.path.join(output_dir, "seed_data.sql")
        ddl_schemas = {
            "accounts": """CREATE TABLE IF NOT EXISTS accounts (
    account_id VARCHAR(32) PRIMARY KEY,
    account_name VARCHAR(128) NOT NULL,
    segment VARCHAR(32) NOT NULL,
    credit_limit DECIMAL(14,2) NOT NULL,
    ar_balance DECIMAL(14,2) NOT NULL,
    created_date DATE NOT NULL
);""",
            "quotes": """CREATE TABLE IF NOT EXISTS quotes (
    quote_id VARCHAR(32) PRIMARY KEY,
    account_id VARCHAR(32) NOT NULL REFERENCES accounts(account_id),
    quote_date DATE NOT NULL,
    valid_until DATE NOT NULL,
    quote_status VARCHAR(32) NOT NULL,
    quote_total DECIMAL(14,2) NOT NULL
);""",
            "quote_lines": """CREATE TABLE IF NOT EXISTS quote_lines (
    quote_line_id VARCHAR(32) PRIMARY KEY,
    quote_id VARCHAR(32) NOT NULL REFERENCES quotes(quote_id),
    product_code VARCHAR(32) NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(14,2) NOT NULL,
    line_total DECIMAL(14,2) NOT NULL
);""",
            "sales_orders": """CREATE TABLE IF NOT EXISTS sales_orders (
    order_id VARCHAR(32) PRIMARY KEY,
    quote_id VARCHAR(32) NOT NULL REFERENCES quotes(quote_id),
    account_id VARCHAR(32) NOT NULL REFERENCES accounts(account_id),
    order_date DATE NOT NULL,
    order_status VARCHAR(32) NOT NULL,
    order_total DECIMAL(14,2) NOT NULL
);""",
            "order_lines": """CREATE TABLE IF NOT EXISTS order_lines (
    order_line_id VARCHAR(32) PRIMARY KEY,
    order_id VARCHAR(32) NOT NULL REFERENCES sales_orders(order_id),
    product_code VARCHAR(32) NOT NULL,
    ordered_qty INT NOT NULL,
    fulfilled_qty INT NOT NULL,
    unit_price DECIMAL(14,2) NOT NULL,
    line_total DECIMAL(14,2) NOT NULL
);""",
            "shipments": """CREATE TABLE IF NOT EXISTS shipments (
    shipment_line_id VARCHAR(32) PRIMARY KEY,
    shipment_id VARCHAR(32) NOT NULL,
    order_id VARCHAR(32) NOT NULL REFERENCES sales_orders(order_id),
    order_line_id VARCHAR(32) NOT NULL REFERENCES order_lines(order_line_id),
    shipped_qty INT NOT NULL,
    ship_date DATE NOT NULL,
    shipment_status VARCHAR(32) NOT NULL
);""",
            "invoices": """CREATE TABLE IF NOT EXISTS invoices (
    invoice_id VARCHAR(32) PRIMARY KEY,
    order_id VARCHAR(32) NOT NULL REFERENCES sales_orders(order_id),
    account_id VARCHAR(32) NOT NULL REFERENCES accounts(account_id),
    invoice_date DATE NOT NULL,
    due_date DATE NOT NULL,
    invoice_total DECIMAL(14,2) NOT NULL,
    paid_amount DECIMAL(14,2) NOT NULL,
    balance_due DECIMAL(14,2) NOT NULL,
    aging_days INT NOT NULL,
    invoice_status VARCHAR(32) NOT NULL
);""",
            "invoice_lines": """CREATE TABLE IF NOT EXISTS invoice_lines (
    invoice_line_id VARCHAR(32) PRIMARY KEY,
    invoice_id VARCHAR(32) NOT NULL REFERENCES invoices(invoice_id),
    order_line_id VARCHAR(32) NOT NULL REFERENCES order_lines(order_line_id),
    invoiced_qty INT NOT NULL,
    unit_price DECIMAL(14,2) NOT NULL,
    line_total DECIMAL(14,2) NOT NULL
);""",
            "payments": """CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(32) PRIMARY KEY,
    invoice_id VARCHAR(32) NOT NULL REFERENCES invoices(invoice_id),
    account_id VARCHAR(32) NOT NULL REFERENCES accounts(account_id),
    payment_date DATE NOT NULL,
    amount DECIMAL(14,2) NOT NULL,
    allocation_ref VARCHAR(64) NOT NULL,
    payment_status VARCHAR(32) NOT NULL
);""",
            "disputes": """CREATE TABLE IF NOT EXISTS disputes (
    dispute_id VARCHAR(32) PRIMARY KEY,
    invoice_id VARCHAR(32) NOT NULL REFERENCES invoices(invoice_id),
    account_id VARCHAR(32) NOT NULL REFERENCES accounts(account_id),
    dispute_date DATE NOT NULL,
    disputed_amount DECIMAL(14,2) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    reflected_in_ar BOOLEAN NOT NULL,
    dispute_status VARCHAR(32) NOT NULL
);""",
            "status_events": """CREATE TABLE IF NOT EXISTS status_events (
    event_id VARCHAR(32) PRIMARY KEY,
    entity_type VARCHAR(32) NOT NULL,
    entity_id VARCHAR(32) NOT NULL,
    from_state VARCHAR(32),
    to_state VARCHAR(32) NOT NULL,
    event_timestamp TIMESTAMP NOT NULL,
    actor VARCHAR(64) NOT NULL
);"""
        }

        def format_sql_val(v):
            if pd.isna(v) or v == "NULL":
                return "NULL"
            if isinstance(v, bool):
                return "TRUE" if v else "FALSE"
            if isinstance(v, (int, float)):
                return str(v)
            escaped = str(v).replace("'", "''")
            return f"'{escaped}'"

        with open(sql_path, "w", encoding="utf-8") as sql_f:
            sql_f.write("-- Full Order-to-Cash (O2C) Relational Schema & Seed Data\n")
            sql_f.write("BEGIN TRANSACTION;\n\n")
            for name, df in tables.items():
                sql_f.write(f"{ddl_schemas[name]}\n")
                if not df.empty:
                    cols = ", ".join(df.columns)
                    records = df.to_dict("records")
                    batch_size = 500
                    for i in range(0, len(records), batch_size):
                        batch = records[i:i + batch_size]
                        val_rows = [
                            "(" + ", ".join(format_sql_val(r[c]) for c in df.columns) + ")"
                            for r in batch
                        ]
                        sql_f.write(f"INSERT INTO {name} ({cols}) VALUES\n" + ",\n".join(val_rows) + ";\n")
                sql_f.write("\n")
            sql_f.write("COMMIT;\n")

        print(f"[+] Full CSV, JSON, and complete SQL seed data generated successfully ({len(orders)} orders, {len(invoices)} invoices, {len(status_events)} events).")

if __name__ == "__main__":
    generator = O2CSyntheticGenerator()
    generator.generate_all()