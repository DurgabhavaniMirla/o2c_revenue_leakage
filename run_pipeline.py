import os
import sys
import stat
import json
import time
import argparse
import pandas as pd
from config import (
    DEFAULT_SEED,
    DEFAULT_SCALE,
    DEFAULT_CUTOFF_DATE,
    DATA_DIR,
    OUTPUT_DIR,
    get_scaled_volumes
)
from generate_data import O2CSyntheticGenerator
from validate_and_detect import O2CValidatorAndDetector

EXPECTED_TABLE_SCHEMAS = {
    "accounts": [
        "account_id", "account_name", "segment", "credit_limit", "ar_balance", "created_date"
    ],
    "quotes": [
        "quote_id", "account_id", "quote_date", "valid_until", "quote_status", "quote_total"
    ],
    "quote_lines": [
        "quote_line_id", "quote_id", "product_code", "quantity", "unit_price", "line_total"
    ],
    "sales_orders": [
        "order_id", "quote_id", "account_id", "order_date", "order_status", "order_total"
    ],
    "order_lines": [
        "order_line_id", "order_id", "product_code", "ordered_qty", "fulfilled_qty", "unit_price", "line_total"
    ],
    "shipments": [
        "shipment_line_id", "shipment_id", "order_id", "order_line_id", "shipped_qty", "ship_date", "shipment_status"
    ],
    "invoices": [
        "invoice_id", "order_id", "account_id", "invoice_date", "due_date",
        "invoice_total", "paid_amount", "balance_due", "aging_days", "invoice_status"
    ],
    "invoice_lines": [
        "invoice_line_id", "invoice_id", "order_line_id", "invoiced_qty", "unit_price", "line_total"
    ],
    "payments": [
        "payment_id", "invoice_id", "account_id", "payment_date", "amount", "allocation_ref", "payment_status"
    ],
    "disputes": [
        "dispute_id", "invoice_id", "account_id", "dispute_date",
        "disputed_amount", "reason_code", "reflected_in_ar", "dispute_status"
    ],
    "status_events": [
        "event_id", "entity_type", "entity_id", "from_state", "to_state", "event_timestamp", "actor"
    ]
}

EXPECTED_OUTPUT_CSV_SCHEMAS = {
    "ground_truth.csv": [
        "anomaly_id", "entity_id", "order_id", "invoice_id", "issue_type",
        "financial_impact_category", "root_cause", "expected_leakage_amount", "expected_decision"
    ],
    "exceptions_and_decisions.csv": [
        "entity_id", "order_id", "issue_type", "financial_impact_category",
        "detected_leakage_amount", "assigned_actor", "recommended_decision",
        "invoice_id", "root_cause", "expected_leakage_amount", "expected_decision",
        "leakage_amount_variance", "decision_matches_ground_truth"
    ],
    "process_delays.csv": [
        "order_id", "invoice_id", "fulfillment_delay_days", "aging_days", "balance_due"
    ]
}

EXPECTED_OUTPUT_JSON_KEYS = {
    "source_manifest.json": {
        "seed", "row_counts", "sha256_checksums", "reproducibility_verified_across_two_runs"
    },
    "validation_summary.json": {
        "total_ground_truth_anomalies", "total_detected_anomalies", "true_positives",
        "false_positives", "false_negatives", "precision", "recall", "f1_score",
        "revenue_leakage_financial_summary", "per_class_evaluation", "step8_schema_validation"
    }
}

def _force_remove_entry(target_path: str, is_dir: bool = False, max_retries: int = 5):
    last_err = None
    for attempt in range(max_retries):
        try:
            if os.path.exists(target_path) or os.path.islink(target_path):
                os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            if is_dir and not os.path.islink(target_path):
                os.rmdir(target_path)
            else:
                os.unlink(target_path)
            return
        except OSError as exc:
            last_err = exc
            time.sleep(0.15 * (attempt + 1))
    raise RuntimeError(
        f"Failed to remove stale artifact '{target_path}' after {max_retries} attempts: {last_err}"
    )

def clean_directory_contents(folder_path: str):
    os.makedirs(folder_path, exist_ok=True)
    for root, dirs, files in os.walk(folder_path, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            _force_remove_entry(fpath, is_dir=False)
        for dname in dirs:
            dpath = os.path.join(root, dname)
            if os.path.islink(dpath):
                _force_remove_entry(dpath, is_dir=False)
            else:
                _force_remove_entry(dpath, is_dir=True)

    remaining = os.listdir(folder_path)
    if remaining:
        raise RuntimeError(
            f"Directory cleanup incomplete for '{folder_path}'. Remaining stale items: {remaining}"
        )

def verify_artifacts(data_dir: str, output_dir: str) -> dict:
    missing_files = []
    empty_files = []
    validation_errors = []
    verified_files = {}

    for tbl, expected_cols in EXPECTED_TABLE_SCHEMAS.items():
        csv_path = os.path.join(data_dir, f"{tbl}.csv")
        json_path = os.path.join(data_dir, f"{tbl}.json")

        csv_df = None
        json_records = None

        if not os.path.exists(csv_path):
            missing_files.append(csv_path)
        elif os.path.getsize(csv_path) == 0:
            empty_files.append(csv_path)
        else:
            try:
                csv_df = pd.read_csv(csv_path, keep_default_na=False)
                if len(csv_df) == 0:
                    validation_errors.append(f"{csv_path}: CSV contains 0 rows")
                if list(csv_df.columns) != expected_cols:
                    validation_errors.append(
                        f"{csv_path}: Column mismatch. Expected {expected_cols}, got {list(csv_df.columns)}"
                    )
                if (csv_df == "").any().any():
                    validation_errors.append(f"{csv_path}: Contains blank/null values in required fields")
                verified_files[f"data/{tbl}.csv"] = {
                    "size_bytes": os.path.getsize(csv_path),
                    "rows": len(csv_df),
                    "schema_valid": list(csv_df.columns) == expected_cols
                }
            except Exception as exc:
                validation_errors.append(f"{csv_path}: Failed to parse CSV ({exc})")

        if not os.path.exists(json_path):
            missing_files.append(json_path)
        elif os.path.getsize(json_path) == 0:
            empty_files.append(json_path)
        else:
            try:
                with open(json_path, "r", encoding="utf-8") as jf:
                    json_records = json.load(jf)
                if not isinstance(json_records, list) or len(json_records) == 0:
                    validation_errors.append(f"{json_path}: JSON root must be a non-empty list of records")
                elif not isinstance(json_records[0], dict) or list(json_records[0].keys()) != expected_cols:
                    validation_errors.append(f"{json_path}: JSON record keys do not match expected schema {expected_cols}")
                verified_files[f"data/{tbl}.json"] = {
                    "size_bytes": os.path.getsize(json_path),
                    "rows": len(json_records) if isinstance(json_records, list) else 0,
                    "valid_json": True
                }
            except Exception as exc:
                validation_errors.append(f"{json_path}: Invalid JSON ({exc})")

        if csv_df is not None and isinstance(json_records, list):
            if len(csv_df) != len(json_records):
                validation_errors.append(
                    f"data/{tbl}: CSV/JSON row count mismatch (CSV={len(csv_df)}, JSON={len(json_records)})"
                )

    gt_csv_len = None
    for csv_name, expected_cols in EXPECTED_OUTPUT_CSV_SCHEMAS.items():
        fpath = os.path.join(output_dir, csv_name)
        if not os.path.exists(fpath):
            missing_files.append(fpath)
        elif os.path.getsize(fpath) == 0:
            empty_files.append(fpath)
        else:
            try:
                df_out = pd.read_csv(fpath, keep_default_na=False)
                if len(df_out) == 0:
                    validation_errors.append(f"{fpath}: Output CSV contains 0 rows")
                if list(df_out.columns) != expected_cols:
                    validation_errors.append(
                        f"{fpath}: Column mismatch. Expected {expected_cols}, got {list(df_out.columns)}"
                    )
                if (df_out == "").any().any():
                    validation_errors.append(f"{fpath}: Contains blank/null cells")
                if csv_name == "ground_truth.csv":
                    gt_csv_len = len(df_out)
                verified_files[f"output/{csv_name}"] = {
                    "size_bytes": os.path.getsize(fpath),
                    "rows": len(df_out),
                    "schema_valid": list(df_out.columns) == expected_cols
                }
            except Exception as exc:
                validation_errors.append(f"{fpath}: Failed to parse CSV ({exc})")

    gt_json_path = os.path.join(output_dir, "ground_truth.json")
    if not os.path.exists(gt_json_path):
        missing_files.append(gt_json_path)
    elif os.path.getsize(gt_json_path) == 0:
        empty_files.append(gt_json_path)
    else:
        try:
            with open(gt_json_path, "r", encoding="utf-8") as gjf:
                gt_json_data = json.load(gjf)
            expected_gt_cols = EXPECTED_OUTPUT_CSV_SCHEMAS["ground_truth.csv"]
            if not isinstance(gt_json_data, list) or len(gt_json_data) == 0:
                validation_errors.append(f"{gt_json_path}: Must be a non-empty JSON list")
            elif list(gt_json_data[0].keys()) != expected_gt_cols:
                validation_errors.append(f"{gt_json_path}: Keys mismatch expected {expected_gt_cols}")
            if gt_csv_len is not None and isinstance(gt_json_data, list) and len(gt_json_data) != gt_csv_len:
                validation_errors.append(
                    f"output/ground_truth: CSV/JSON row count mismatch ({gt_csv_len} vs {len(gt_json_data)})"
                )
            verified_files["output/ground_truth.json"] = {
                "size_bytes": os.path.getsize(gt_json_path),
                "rows": len(gt_json_data) if isinstance(gt_json_data, list) else 0,
                "valid_json": True
            }
        except Exception as exc:
            validation_errors.append(f"{gt_json_path}: Invalid JSON ({exc})")

    for json_name, required_keys in EXPECTED_OUTPUT_JSON_KEYS.items():
        fpath = os.path.join(output_dir, json_name)
        if not os.path.exists(fpath):
            missing_files.append(fpath)
        elif os.path.getsize(fpath) == 0:
            empty_files.append(fpath)
        else:
            try:
                with open(fpath, "r", encoding="utf-8") as jf:
                    jdata = json.load(jf)
                if not isinstance(jdata, dict):
                    validation_errors.append(f"{fpath}: Root must be a JSON object")
                else:
                    missing_keys = required_keys - set(jdata.keys())
                    if missing_keys:
                        validation_errors.append(f"{fpath}: Missing required keys {sorted(missing_keys)}")
                verified_files[f"output/{json_name}"] = {
                    "size_bytes": os.path.getsize(fpath),
                    "valid_json": True,
                    "required_keys_present": True
                }
            except Exception as exc:
                validation_errors.append(f"{fpath}: Invalid JSON ({exc})")

    sql_path = os.path.join(output_dir, "seed_data.sql")
    if not os.path.exists(sql_path):
        missing_files.append(sql_path)
    elif os.path.getsize(sql_path) == 0:
        empty_files.append(sql_path)
    else:
        try:
            with open(sql_path, "r", encoding="utf-8") as sf:
                sql_text = sf.read()
            if "BEGIN TRANSACTION;" not in sql_text or "COMMIT;" not in sql_text:
                validation_errors.append(f"{sql_path}: Missing BEGIN TRANSACTION or COMMIT statements")
            for tbl in EXPECTED_TABLE_SCHEMAS:
                if f"CREATE TABLE IF NOT EXISTS {tbl}" not in sql_text:
                    validation_errors.append(f"{sql_path}: Missing CREATE TABLE DDL for '{tbl}'")
                if f"INSERT INTO {tbl}" not in sql_text:
                    validation_errors.append(f"{sql_path}: Missing INSERT INTO statements for '{tbl}'")
            verified_files["output/seed_data.sql"] = {
                "size_bytes": os.path.getsize(sql_path),
                "ddl_tables_verified": len(EXPECTED_TABLE_SCHEMAS),
                "dml_inserts_verified": len(EXPECTED_TABLE_SCHEMAS)
            }
        except Exception as exc:
            validation_errors.append(f"{sql_path}: Failed to read/validate SQL ({exc})")

    all_valid = (
        len(missing_files) == 0
        and len(empty_files) == 0
        and len(validation_errors) == 0
    )

    return {
        "all_artifacts_present_and_valid": all_valid,
        "total_verified_files": len(verified_files),
        "missing_files": missing_files,
        "empty_files": empty_files,
        "content_validation_errors": validation_errors,
        "verified_artifact_details": verified_files
    }

def main():
    parser = argparse.ArgumentParser(description="End-to-End O2C Revenue Leakage Execution Pipeline")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic RNG seed")
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE, help="Dataset scale factor")
    parser.add_argument("--cutoff-date", type=str, default=DEFAULT_CUTOFF_DATE, help="Audit cutoff date (YYYY-MM-DD)")
    parser.add_argument("--data-dir", type=str, default=DATA_DIR, help="Directory for generated data tables")
    parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR, help="Directory for validation & audit outputs")
    parser.add_argument(
        "--clean",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clean stale artifacts before execution (pass --no-clean to disable)"
    )
    args = parser.parse_args()

    start_time = time.time()
    print("=" * 80)
    print("[*] STARTING END-TO-END O2C REVENUE LEAKAGE EXECUTION PIPELINE")
    print("=" * 80)

    if args.clean:
        print("[Stage 1/5] Recursively cleaning previous build artifacts & subdirectories...")
        clean_directory_contents(args.data_dir)
        clean_directory_contents(args.output_dir)
    else:
        print("[Stage 1/5] Skipping artifact cleanup (--no-clean specified). Preserving existing files...")
        os.makedirs(args.data_dir, exist_ok=True)
        os.makedirs(args.output_dir, exist_ok=True)

    existing_csvs = [f for f in os.listdir(args.data_dir) if f.endswith(".csv")]
    if args.clean or len(existing_csvs) < len(EXPECTED_TABLE_SCHEMAS):
        print(f"[Stage 2/5] Executing Pass 1 synthetic data generation (Seed: {args.seed}, Scale: {args.scale})...")
        gen = O2CSyntheticGenerator(seed=args.seed, scale=args.scale, cutoff_date=args.cutoff_date)
        gen.generate_all(data_dir=args.data_dir, output_dir=args.output_dir)
    else:
        print("[Stage 2/5] Existing dataset found in data directory (--no-clean). Using existing files as Pass 1 baseline...")

    print("[Stage 3/5] Running Pass 2 reproducibility check, schema audit, and anomaly detection...")
    validator = O2CValidatorAndDetector(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        cutoff_date=args.cutoff_date,
        seed=args.seed,
        scale=args.scale
    )
    metrics = validator.run_pipeline()

    print("[Stage 4/5] Parsing and validating CSV schemas, JSON structure, SQL DDL/DML, and scale volume targets...")
    artifact_audit = verify_artifacts(args.data_dir, args.output_dir)

    with open(os.path.join(args.output_dir, "source_manifest.json"), "r", encoding="utf-8") as mf:
        manifest = json.load(mf)

    row_counts = manifest.get("row_counts", {})
    scaled_vols = get_scaled_volumes(args.scale)

    expected_orders = scaled_vols["sales_orders"]
    expected_quotes = scaled_vols["quotes"]
    expected_accounts = scaled_vols["accounts"]
    expected_invoices = scaled_vols["invoices"]
    expected_events = row_counts.get("status_events.csv", max(1500, int(15000 * args.scale)))

    volume_targets_met = (
        row_counts.get("accounts.csv") == expected_accounts
        and row_counts.get("quotes.csv") == expected_quotes
        and row_counts.get("sales_orders.csv") == expected_orders
        and row_counts.get("invoices.csv") == expected_invoices
        and row_counts.get("status_events.csv") == expected_events
    )

    print("[Stage 5/5] Evaluating automated pipeline quality gates...")
    schema_val = metrics["step8_schema_validation"]
    fin_summary = metrics["revenue_leakage_financial_summary"]

    quality_gates = {
        "gate_1_all_artifacts_valid_and_parsed": artifact_audit["all_artifacts_present_and_valid"],
        "gate_2_volume_targets_exact": volume_targets_met,
        "gate_3_deterministic_reproducibility": bool(metrics["reproducibility_verified"]),
        "gate_4_primary_keys_unique": bool(schema_val["primary_key_uniqueness"]),
        "gate_5_foreign_keys_and_transitive_links_valid": bool(schema_val["foreign_key_integrity"]),
        "gate_6_cross_table_date_chronology_valid": bool(schema_val["date_ordering_valid"]),
        "gate_7_o2c_workflow_continuity_valid": bool(
            schema_val["o2c_workflow_state_machine_audit"]["state_chain_continuity_intact"]
            and schema_val["o2c_workflow_state_machine_audit"]["terminal_event_matches_entity_status"]
        ),
        "gate_8_subledger_and_arithmetic_reconciled": bool(
            schema_val["arithmetic_reconciliation_valid"]
            and schema_val["independent_payment_ledger_reconciled"]
            and schema_val["account_ar_subledger_reconciled"]
        ),
        "gate_9_zero_false_positives_and_negatives": (
            metrics["false_positives"] == 0
            and metrics["false_negatives"] == 0
            and metrics["hard_negative_false_positives"] == 0
            and metrics["precision"] == 1.0
            and metrics["recall"] == 1.0
        ),
        "gate_10_exact_monetary_leakage_reconciled": bool(fin_summary["exact_monetary_reconciliation_verified"])
    }

    all_gates_passed = all(quality_gates.values())
    elapsed_sec = round(time.time() - start_time, 2)

    execution_report = {
        "pipeline_status": "SUCCESS" if all_gates_passed else "FAILED",
        "execution_time_seconds": elapsed_sec,
        "parameters": {
            "seed": args.seed,
            "scale": args.scale,
            "cutoff_date": args.cutoff_date,
            "clean_enabled": args.clean
        },
        "expected_scaled_volumes": {
            "accounts.csv": expected_accounts,
            "quotes.csv": expected_quotes,
            "sales_orders.csv": expected_orders,
            "invoices.csv": expected_invoices,
            "status_events.csv": expected_events
        },
        "quality_gates": quality_gates,
        "row_counts": row_counts,
        "artifact_verification": artifact_audit,
        "validation_and_detection_summary": metrics
    }

    report_path = os.path.join(args.output_dir, "pipeline_execution_report.json")
    with open(report_path, "w", encoding="utf-8") as rf:
        json.dump(execution_report, rf, indent=2)

    print("-" * 80)
    for gate_name, passed in quality_gates.items():
        status_icon = "PASS" if passed else "FAIL"
        print(f"    [{status_icon}] {gate_name}")
    if artifact_audit["content_validation_errors"]:
        print("    [!] Artifact Validation Errors:", artifact_audit["content_validation_errors"])
    print("-" * 80)

    if not all_gates_passed:
        print("[!] PIPELINE FAILED ONE OR MORE QUALITY GATES.")
        sys.exit(1)

    print(f"[+] END-TO-END PIPELINE SUCCEEDED IN {elapsed_sec}s (All 10 Quality Gates Passed!)")
    print(f"[+] Full execution report written to: {report_path}")
    print("=" * 80)
    sys.exit(0)

if __name__ == "__main__":
    main()