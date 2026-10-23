import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checks


def bill(**over):
    base = {"is_electricity_bill": True, "billing_month": "OCT 25", "protected_status": "non-protected",
            "previous_reading": 1000, "present_reading": 1250, "units_consumed": 250, "billing_days": 30,
            "total_payable": 5000,
            "unit_history": [{"month": m, "units": 250} for m in ("SEP 25", "AUG 25", "JUL 25")]}
    base.update(over)
    return checks.normalize_extraction(base)


def sev(data, check_id):
    return {f["id"]: f for f in checks.run_checks(data)}.get(check_id)


class NumberTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(checks.to_number("1,234"), 1234)
        self.assertEqual(checks.to_number("Rs. 18,500.50"), 18500.5)
        self.assertEqual(checks.to_number("۱۲۳"), 123)
        self.assertIsNone(checks.to_number("abc"))
        self.assertIsNone(checks.to_number(None))


class CheckTests(unittest.TestCase):
    def test_readings_ok(self):
        self.assertEqual(sev(bill(), "readings")["severity"], "ok")

    def test_readings_mismatch_warns(self):
        self.assertEqual(sev(bill(units_consumed=400), "readings")["severity"], "warn")

    def test_meter_multiplier_is_info(self):
        self.assertEqual(sev(bill(units_consumed=500), "readings")["severity"], "info")

    def test_long_cycle_warns_and_quotes_number(self):
        flag = sev(bill(billing_days=33), "billing_days")
        self.assertEqual(flag["severity"], "warn")
        self.assertIn("33", flag["detail"])

    def test_short_cycle_info(self):
        self.assertEqual(sev(bill(billing_days=25), "billing_days")["severity"], "info")

    def test_usage_spike(self):
        d = bill(present_reading=1400, units_consumed=400)
        self.assertEqual(sev(d, "history")["severity"], "warn")

    def test_usage_needs_three_months(self):
        d = bill(unit_history=[{"month": "SEP 25", "units": 100}])
        self.assertIsNone(sev(d, "history"))

    def test_protected_status_worth_verifying(self):
        d = bill(present_reading=1150, units_consumed=150,
                 unit_history=[{"month": m, "units": 120} for m in ("SEP 25", "AUG 25", "JUL 25")])
        self.assertEqual(sev(d, "protected")["severity"], "warn")

    def test_protected_with_high_units_info(self):
        self.assertEqual(sev(bill(protected_status="protected"), "protected")["severity"], "info")

    def test_net_metering_info(self):
        self.assertEqual(sev(bill(export_units=40), "net_metering")["severity"], "info")

    def test_unreadable_info(self):
        d = bill(unreadable=["billing_days"], billing_days=None)
        self.assertEqual(sev(d, "readability")["severity"], "info")

    def test_warn_sorted_first(self):
        self.assertEqual(checks.run_checks(bill(billing_days=40))[0]["severity"], "warn")


if __name__ == "__main__":
    unittest.main()