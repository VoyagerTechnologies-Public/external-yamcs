"""Unit tests for yamcs_commander.py's verify-step engine, in particular the
"approx" cross-parameter condition added for ADCS ground-truth verification
(issue #8). No network access -- the commander is mocked.

Run directly: python3 yamcs/test_yamcs_commander_verify.py
"""
import pathlib
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import yamcs_commander as yc  # noqa: E402


def _commander_returning(values_by_param):
    """A mock commander whose get_parameter_value(param) returns
    {"value": values_by_param[param]} or raises RuntimeError/
    ParameterNotFoundError if the mapped value is such an exception."""
    commander = MagicMock()

    def _get(param):
        value = values_by_param[param]
        if isinstance(value, Exception):
            raise value
        return {"value": value}

    commander.get_parameter_value.side_effect = _get
    return commander


class TestApproxCondition(unittest.TestCase):
    def test_passes_within_tolerance(self):
        commander = _commander_returning({"/ADCS/SUN_X": 0.991, "/SIM_42_TRUTH/SVB_1": 0.990})
        step = {"condition": [{"parameter": "/ADCS/SUN_X", "operator": "approx",
                                "reference_parameter": "/SIM_42_TRUTH/SVB_1", "tolerance": 0.01}],
                "timeout": 100}
        result = yc._run_verify_step(commander, step)
        self.assertEqual(result["status"], "passed")

    def test_fails_outside_tolerance_after_timeout(self):
        commander = _commander_returning({"/ADCS/SUN_X": 0.5, "/SIM_42_TRUTH/SVB_1": 0.990})
        step = {"condition": [{"parameter": "/ADCS/SUN_X", "operator": "approx",
                                "reference_parameter": "/SIM_42_TRUTH/SVB_1", "tolerance": 0.01}],
                "timeout": 50}
        result = yc._run_verify_step(commander, step)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["actual"]["/ADCS/SUN_X"], 0.5)
        self.assertEqual(result["actual"]["/SIM_42_TRUTH/SVB_1"], 0.990)

    def test_nonexistent_reference_parameter_fails_immediately(self):
        commander = _commander_returning({
            "/ADCS/SUN_X": 0.99,
            "/SIM_42_TRUTH/NOT_REAL": yc.ParameterNotFoundError("no such parameter"),
        })
        step = {"condition": [{"parameter": "/ADCS/SUN_X", "operator": "approx",
                                "reference_parameter": "/SIM_42_TRUTH/NOT_REAL", "tolerance": 0.01}],
                "timeout": 5000}
        result = yc._run_verify_step(commander, step)
        self.assertEqual(result["status"], "failed")
        # Must not have polled until the (long) timeout for an unresolvable parameter.
        self.assertLessEqual(commander.get_parameter_value.call_count, 2)

    def test_no_sample_yet_keeps_polling_then_times_out(self):
        commander = _commander_returning({
            "/ADCS/SUN_X": RuntimeError("no value received yet"),
            "/SIM_42_TRUTH/SVB_1": 0.990,
        })
        step = {"condition": [{"parameter": "/ADCS/SUN_X", "operator": "approx",
                                "reference_parameter": "/SIM_42_TRUTH/SVB_1", "tolerance": 0.01}],
                "timeout": 50}
        result = yc._run_verify_step(commander, step)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["actual"]["/ADCS/SUN_X"])


class TestLiteralConditionRegression(unittest.TestCase):
    """The refactor that introduced _read_param() must not change behavior
    for the pre-existing literal-value operators."""

    def test_eq_still_passes(self):
        commander = _commander_returning({"/ADCS/CMD_COUNT": 1.0})
        step = {"condition": [{"parameter": "/ADCS/CMD_COUNT", "operator": "eq", "value": "1"}],
                "timeout": 100}
        result = yc._run_verify_step(commander, step)
        self.assertEqual(result["status"], "passed")

    def test_unresolvable_parameter_fails_fast_not_by_timeout(self):
        commander = _commander_returning({
            "/ADCS/BOGUS": yc.ParameterNotFoundError("no such parameter"),
        })
        step = {"condition": [{"parameter": "/ADCS/BOGUS", "operator": "eq", "value": "1"}],
                "timeout": 5000}
        result = yc._run_verify_step(commander, step)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(commander.get_parameter_value.call_count, 1)


if __name__ == "__main__":
    unittest.main()
