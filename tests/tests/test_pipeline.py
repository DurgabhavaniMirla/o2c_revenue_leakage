import os
import json
import unittest
from config import DEFAULT_SEED, DEFAULT_CUTOFF_DATE, get_scaled_volumes
from run_pipeline import verify_artifacts

class TestO2CPipeline(unittest.TestCase):
    def test_central_config_volumes(self):
        vols = get_scaled_volumes(1.0)
        self.assertEqual(vols["accounts"], 1500)
        self.assertEqual(vols["quotes"], 10000)
        self.assertEqual(vols["sales_orders"], 7000)
        self.assertEqual(vols["invoices"], 8000)
        self.assertEqual(vols["status_events"], 15000)

    def test_artifacts_and_quality_gates(self):
        audit = verify_artifacts("data", "output")
        self.assertTrue(audit["all_artifacts_present_and_valid"], f"Errors: {audit['content_validation_errors']}")

        report_path = os.path.join("output", "pipeline_execution_report.json")
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        self.assertEqual(report["pipeline_status"], "SUCCESS")
        for gate, passed in report["quality_gates"].items():
            self.assertTrue(passed, f"Quality gate failed: {gate}")

if __name__ == "__main__":
    unittest.main()