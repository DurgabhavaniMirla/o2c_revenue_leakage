# Order-to-Cash (O2C) Relational Schema & Complete Data Dictionary

This document defines the exact columns, SQL/Pandas data types, Primary Keys (`PK`), Foreign Keys (`FK`), allowed enum constraints, and cross-table relationships across all **11 core O2C relational tables** (`data/*.csv`, `data/*.json`, and `output/seed_data.sql`) and **audit output tables** (`output/*.csv`).

---

## 1. Entity-Relationship & Cross-Table Integrity Summary

* **Customer & Quote Hierarchy:** `accounts.account_id` $\leftarrow$ `quotes.account_id` $\leftarrow$ `quote_lines.quote_id`
* **Order & Line Hierarchy:** `quotes.quote_id` $\leftarrow$ `sales_orders.quote_id` $\leftarrow$ `order_lines.order_id`
* **Fulfillment (Shipment-to-Order-Line Relationship):**
  * `shipments.order_id` $\rightarrow$ `sales_orders.order_id`
  * `shipments.order_line_id` $\rightarrow$ `order_lines.order_line_id`
  * Granularity: `shipment_line_id` is the Primary Key (`PK`); multiple shipment lines can share a `shipment_id` header, and split shipments can fulfill a single `order_line_id` across multiple dates.
* **Billing (Invoice & Invoice-Line Relationships):**
  * `invoices.order_id` $\rightarrow$ `sales_orders.order_id` and `invoices.account_id` $\rightarrow$ `accounts.account_id`
  * `invoice_lines.invoice_id` $\rightarrow$ `invoices.invoice_id`
  * `invoice_lines.order_line_id` $\rightarrow$ `order_lines.order_line_id` (links billed quantities directly to fulfilled order lines).
* **Cash Application (Payment & Allocation Relationships):**
  * `payments.invoice_id` $\rightarrow$ `invoices.invoice_id`
  * `payments.account_id` $\rightarrow$ `accounts.account_id`
  * `payments.allocation_ref` tracks the remittance/settlement allocation reference per invoice; independent reconciliation verifies `invoices.invoice_total - SUM(payments.amount) == invoices.balance_due`.
* **Dispute Management (Dispute-to-Invoice Relationships):**
  * `disputes.invoice_id` $\rightarrow$ `invoices.invoice_id`
  * `disputes.account_id` $\rightarrow$ `accounts.account_id`
  * `disputes.reflected_in_ar` (`BOOLEAN`) tracks whether open disputed amounts (`dispute_status = 'Open'`) have been synchronized to the Accounts Receivable sub-ledger hold.
* **Workflow Audit Trail (Polymorphic Event & State-Transition Relationships):**
  * `status_events.entity_id` references `quotes.quote_id` when `entity_type = 'Quote'` and `sales_orders.order_id` when `entity_type = 'SalesOrder'`.
  * Enforces chronological monotonicity (`event_timestamp`) and unbroken state-chain continuity (`step[i].to_state == step[i+1].from_state`).

---

## 2. Core Relational Tables (`data/` & `output/seed_data.sql`)

### Table 1: `accounts` (`data/accounts.csv` | `1,500` rows at 1.0x scale)
Customer master record and Accounts Receivable (AR) sub-ledger summary.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `account_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique customer identifier (`ACC-2026-XXXXXX`). |
| `account_name` | `VARCHAR(128)` | `string` | `NOT NULL` | Registered legal name of the customer entity. |
| `segment` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Customer tier: `'Enterprise'`, `'Mid-Market'`, or `'SMB'`. |
| `credit_limit` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Maximum authorized credit exposure (`5000000.00`, `1000000.00`, or `250000.00`). |
| `ar_balance` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `>= 0` | Open AR sub-ledger balance; must reconcile with `SUM(invoices.balance_due)` per `account_id`. |
| `created_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Account onboarding date (`created_date <= quotes.quote_date`). |

---

### Table 2: `quotes` (`data/quotes.csv` | `10,000` rows at 1.0x scale)
Commercial price quotes issued to prospective and existing customer accounts.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `quote_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique quote header identifier (`QTE-2026-XXXXXX`). |
| `account_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `accounts(account_id)` | Customer account receiving the quote (`NOT NULL`). |
| `quote_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Date quote was generated (`accounts.created_date <= quote_date <= valid_until`). |
| `valid_until` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Quote expiration date (`quote_date + 30 days`). |
| `quote_status` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Allowed values: `'Draft'`, `'Sent'`, `'Accepted'`, `'Rejected'`, `'Expired'`. |
| `quote_total` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Header total; must equal `SUM(quote_lines.line_total)` for `quote_id`. |

---

### Table 3: `quote_lines` (`data/quote_lines.csv`)
Product line items and unit pricing associated with each quote header.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `quote_line_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique quote line identifier (`QLN-2026-XXXXXX`). |
| `quote_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `quotes(quote_id)` | Parent quote header reference (`NOT NULL`). |
| `product_code` | `VARCHAR(32)` | `string` | `NOT NULL` | Catalog SKU identifier (`PRD-001` through `PRD-050`). |
| `quantity` | `INT` | `int64` | `NOT NULL`, `> 0` | Quoted product quantity. |
| `unit_price` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Contracted unit price for the SKU. |
| `line_total` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Extended line amount; must equal `ROUND(quantity * unit_price, 2)`. |

---

### Table 4: `sales_orders` (`data/sales_orders.csv` | `7,000` rows at 1.0x scale)
Confirmed customer orders converted from accepted quotes (`quotes.quote_status = 'Accepted'`).

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `order_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique sales order identifier (`SO-2026-XXXXXX`). |
| `quote_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `quotes(quote_id)` | Originating accepted quote (`NOT NULL`). |
| `account_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `accounts(account_id)` | Customer account (`must match quotes.account_id`). |
| `order_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Order booking date (`quotes.quote_date <= order_date <= quotes.valid_until`). |
| `order_status` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Allowed values: `'Created'`, `'Fulfilled'`, `'Partially_Fulfilled'`, `'Invoiced'`, `'Closed'`. |
| `order_total` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Total contracted order value; equals `SUM(order_lines.line_total)`. |

---

### Table 5: `order_lines` (`data/order_lines.csv`)
Contracted line items, ordered quantities, and cumulative fulfilled quantities per sales order.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `order_line_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique sales order line identifier (`OLN-2026-XXXXXX`). |
| `order_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `sales_orders(order_id)` | Parent sales order reference (`NOT NULL`). |
| `product_code` | `VARCHAR(32)` | `string` | `NOT NULL` | Product SKU code (`PRD-001` through `PRD-050`). |
| `ordered_qty` | `INT` | `int64` | `NOT NULL`, `> 0` | Contracted quantity ordered by the customer. |
| `fulfilled_qty` | `INT` | `int64` | `NOT NULL`, `>= 0` | Cumulative quantity shipped (`equals SUM(shipments.shipped_qty)` for `order_line_id`). |
| `unit_price` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Contracted unit price per item. |
| `line_total` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Extended order line value; equals `ROUND(ordered_qty * unit_price, 2)`. |

---

### Table 6: `shipments` (`data/shipments.csv`)
Warehouse fulfillment and delivery records linked to both `sales_orders` and `order_lines`.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `shipment_line_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique shipment line identifier (`SHPL-2026-XXXXXX`). |
| `shipment_id` | `VARCHAR(32)` | `string` | `NOT NULL` (Header Group ID) | Shipment delivery header ID (`SHP-2026-XXXXXX`); all lines sharing a `shipment_id` have identical `order_id`, `ship_date`, and `shipment_status`. |
| `order_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `sales_orders(order_id)` | Parent sales order (`must match order_lines.order_id`). |
| `order_line_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `order_lines(order_line_id)` | Specific order line being fulfilled (`NOT NULL`). |
| `shipped_qty` | `INT` | `int64` | `NOT NULL`, `> 0` | Quantity dispatched in this delivery tranche. |
| `ship_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Dispatch date (`sales_orders.order_date <= ship_date <= invoices.invoice_date`). |
| `shipment_status` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Allowed values: `'Delivered'`, `'Partial'`. |

---

### Table 7: `invoices` (`data/invoices.csv` | `8,000` rows at 1.0x scale)
Customer billing headers, payment status, balance due, and AR aging metrics.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `invoice_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique invoice header identifier (`INV-2026-XXXXXX`). |
| `order_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `sales_orders(order_id)` | Associated sales order (`NOT NULL`). |
| `account_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `accounts(account_id)` | Billed customer account (`must match sales_orders.account_id`). |
| `invoice_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Billing issue date (`shipments.ship_date <= invoice_date <= due_date`). |
| `due_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Payment due date (`invoice_date + 30 days`). |
| `invoice_total` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Gross billed amount; must equal `SUM(invoice_lines.line_total)` for `invoice_id`. |
| `paid_amount` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `>= 0` | Recorded header paid amount (independently audited against `SUM(payments.amount)`). |
| `balance_due` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `>= 0` | Open unpaid balance (`invoice_total - paid_amount`). |
| `aging_days` | `INT` | `int64` | `NOT NULL`, `>= 0` | Days past `due_date` as of `cutoff_date` (`2026-10-31`) when `balance_due > 0`, else `0`. |
| `invoice_status` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Allowed values: `'Issued'`, `'Paid'`, `'Overdue'`, `'Disputed'`. |

---

### Table 8: `invoice_lines` (`data/invoice_lines.csv`)
Line-level billing records linking each invoice to the specific `order_line_id` fulfilled.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `invoice_line_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique invoice line identifier (`ILN-2026-XXXXXX`). |
| `invoice_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `invoices(invoice_id)` | Parent invoice header reference (`NOT NULL`). |
| `order_line_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `order_lines(order_line_id)` | Fulfilled order line being billed (`order_lines.order_id == invoices.order_id`). |
| `invoiced_qty` | `INT` | `int64` | `NOT NULL`, `> 0` | Quantity billed on this invoice line (compared against `shipped_qty` for over/underbilling). |
| `unit_price` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Billed unit price (matches `order_lines.unit_price`). |
| `line_total` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Extended billed line total; must equal `ROUND(invoiced_qty * unit_price, 2)`. |

---

### Table 9: `payments` (`data/payments.csv`)
Customer cash receipts and remittance allocations applied against invoices.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `payment_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique payment transaction identifier (`PAY-2026-XXXXXX`). |
| `invoice_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `invoices(invoice_id)` | Target invoice receiving the cash allocation (`NOT NULL`). |
| `account_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `accounts(account_id)` | Paying customer account (`must match invoices.account_id`). |
| `payment_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Cash settlement date (`payment_date >= invoices.invoice_date`). |
| `amount` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Allocated payment amount (`SUM(amount) > invoice_total` indicates overpayment anomaly). |
| `allocation_ref` | `VARCHAR(64)` | `string` | `NOT NULL` | Bank remittance / ERP allocation reference (`ALLOC-XXXXXX`; duplicate `(invoice_id, amount, allocation_ref)` flags `PAYMENT_ALLOCATED_TWICE`). |
| `payment_status` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Allowed values: `'Allocated'`, `'Duplicate_Allocation'`. |

---

### Table 10: `disputes` (`data/disputes.csv`)
Customer-initiated billing disputes and AR sub-ledger hold synchronization records.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
| :--- | :--- | :--- | :--- | :--- |
| `dispute_id` | `VARCHAR(32)` | `string` | **PRIMARY KEY**, `NOT NULL` | Unique dispute case identifier (`DSP-2026-XXXXXX`). |
| `invoice_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `invoices(invoice_id)` | Disputed invoice reference (`NOT NULL`). |
| `account_id` | `VARCHAR(32)` | `string` | **FOREIGN KEY** $\rightarrow$ `accounts(account_id)` | Customer account (`must match invoices.account_id`). |
| `dispute_date` | `DATE` | `string (YYYY-MM-DD)` | `NOT NULL` | Date dispute was logged (`dispute_date >= invoices.invoice_date`). |
| `disputed_amount` | `DECIMAL(14,2)` | `float64` | `NOT NULL`, `> 0` | Monetary value under dispute (`<= invoices.invoice_total`). |
| `reason_code` | `VARCHAR(64)` | `string` | `NOT NULL` | Standardized dispute reason (e.g., `'Pricing_Error'`, `'Tax_Adjustment_Settled'`). |
| `reflected_in_ar` | `BOOLEAN` | `bool` | `NOT NULL` | Whether the dispute hold is reflected in AR (`False` on `'Open'` dispute with unpaid balance flags `DISPUTE_NOT_REFLECTED_IN_AR`). |
| `dispute_status` | `VARCHAR(32)` | `string` | `NOT NULL`, Enum | Allowed values: `'Open'`, `'Resolved'`. |

---

### Table 11: `status_events` (`data/status_events.csv` | `15,000` rows at 1.0x scale)
Immutable state-machine transition log tracking `Quote` and `SalesOrder` lifecycle progressions.

| Column Name | SQL Type | Pandas Type | Key / Constraint | Description & Validation Rules |
|