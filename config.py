import os

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "data"
OUTPUT_DIR = "output"

# Deterministic Pipeline Defaults
DEFAULT_SEED = 20261022
DEFAULT_SCALE = 1.0
DEFAULT_CUTOFF_DATE = "2026-10-31"

# Base Volume Targets (at 1.0x Scale)
BASE_ACCOUNTS = 1500
BASE_QUOTES = 10000
BASE_ORDERS = 7000
BASE_INVOICES = 8000
BASE_EVENTS = 15000

# SLA & Detection Guardrail Thresholds
UNDERBILLING_SLA_DAYS = 7
FULFILLMENT_SLA_DAYS = 14
DELAYED_FULFILLMENT_THRESHOLD_DAYS = 10
OVERDUE_AGING_THRESHOLD_DAYS = 60
MONETARY_TOLERANCE = 0.01

def get_scaled_volumes(scale: float = DEFAULT_SCALE) -> dict:
    """Returns exact expected row counts for any dataset scale factor."""
    orders = max(365, int(BASE_ORDERS * scale))
    quotes = max(orders, int(BASE_QUOTES * scale))
    accounts = max(50, int(BASE_ACCOUNTS * scale))
    invoices = max(orders + 65, int(BASE_INVOICES * scale))
    events = max(1500, int(BASE_EVENTS * scale))
    return {
        "accounts": accounts,
        "quotes": quotes,
        "sales_orders": orders,
        "invoices": invoices,
        "status_events": events
    }