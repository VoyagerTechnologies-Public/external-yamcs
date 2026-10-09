"""Unit tests for yamcs_commander.py's verify-step engine, in particular the
"approx" cross-parameter condition added for ADCS ground-truth verification
(issue #8). No network access -- the commander is mocked.

Run directly: python3 yamcs/test_yamcs_commander_verify.py
"""
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'tools'))

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


class TestFreshEPSVerification(unittest.TestCase):
    def test_eps_initialization_uses_fsw_enable_state(self):
        stack={'steps':[{'type':'command','name':'/DEMO/DEMO_ENABLE_CC','comment':'Enable if disabled: /DEMO/DEVICE_ENABLED'}]}
        for value,issued in ((1,False),('ENABLED',False),(0,True),('DISABLED',True)):
            with self.subTest(value=value):
                commander=_commander_returning({'/DEMO/DEVICE_ENABLED':value})
                with patch.object(yc,'_run_command_step',return_value={'status':'passed'}) as command:
                    result=yc.run_stack(commander,stack,stack_name='EPS initialization')
                self.assertTrue(result['passed'])
                self.assertEqual(command.called,issued)
        commander=_commander_returning({'/DEMO/DEVICE_ENABLED':'UNKNOWN'})
        with patch.object(yc,'_run_command_step') as command:
            result=yc.run_stack(commander,stack,stack_name='EPS initialization')
        self.assertFalse(result['passed']);command.assert_not_called()

    def test_initialization_waits_for_startup_telemetry_without_retrying_enable(self):
        commander=MagicMock()
        commander.get_parameter_value.side_effect=[RuntimeError('no telemetry yet'),{'value':0}]
        stack={'steps':[{'type':'command','name':'/DEMO/DEMO_ENABLE_CC','comment':'Enable if disabled: /DEMO/DEVICE_ENABLED'}]}
        with patch.object(yc.time,'sleep'), patch.object(yc,'_run_command_step',return_value={'status':'passed'}) as command:
            result=yc.run_stack(commander,stack,stack_name='startup')
        self.assertTrue(result['passed']);command.assert_called_once()
        commander.get_parameter_value.side_effect=RuntimeError('no telemetry')
        with patch.object(yc.time,'monotonic',side_effect=[0,10]):
            with self.assertRaisesRegex(RuntimeError,'unavailable'):
                yc._wait_for_fsw_enable_state(commander,'/DEMO/DEVICE_ENABLED')
        commander.get_parameter_value.side_effect=yc.ParameterNotFoundError('invalid parameter')
        with patch.object(yc.time,'sleep') as sleep:
            with self.assertRaises(yc.ParameterNotFoundError):
                yc._wait_for_fsw_enable_state(commander,'/DEMO/MISSING')
        sleep.assert_not_called()
    def run_check(self, values, counter=None):
        commander=MagicMock()
        rows=iter(values)
        last=values[-1]
        commander.get_parameter_value.side_effect=lambda _: next(rows,last)
        return yc._run_verify_step(commander,{'condition':[{'parameter':'/DEMO/DEVICE_COUNT','operator':'gt','value':'0'}],'timeout':25},require_fresh=True,transaction_baselines=counter)
    def test_cached_hk_cannot_prove_responsiveness(self):
        row={'value':10,'raw':{'acquisitionTime':'2026-10-06T00:00:00Z'}}
        self.assertEqual(self.run_check([row])['status'],'failed')
    def test_fresh_timestamp_with_old_transaction_count_fails(self):
        row={'value':10,'raw':{'acquisitionTime':'2026-10-06T00:00:00Z'}}
        newer={'value':10,'raw':{'acquisitionTime':'2026-10-06T00:00:01Z'}}
        self.assertEqual(self.run_check([row,newer],{'/DEMO/DEVICE_COUNT':10})['status'],'failed')
    def test_new_successful_device_transaction_passes(self):
        row={'value':10,'raw':{'acquisitionTime':'2026-10-06T00:00:00Z'}}
        newer={'value':11,'raw':{'acquisitionTime':'2026-10-06T00:00:01Z'}}
        self.assertEqual(self.run_check([row,newer],{'/DEMO/DEVICE_COUNT':10})['status'],'passed')

    def test_prompt_hk_response_is_fresh_relative_to_command(self):
        commander=MagicMock()
        commander.get_parameter_value.return_value={'value':11,'raw':{'acquisitionTime':'2026-10-06T00:00:01Z'}}
        step={'condition':[{'parameter':'/DEMO/DEVICE_COUNT','operator':'gt','value':'0'}],'timeout':25}
        result=yc._run_verify_step(commander,step,require_fresh=True,
                    transaction_baselines={'/DEMO/DEVICE_COUNT':10},
                    acquisition_baselines={'/DEMO':'2026-10-06T00:00:00Z'})
        self.assertEqual(result['status'],'passed')
        self.assertEqual(commander.get_parameter_value.call_count,1)

    def test_non_counter_string_comparisons_keep_standard_stack_semantics(self):
        commander=_commander_returning({'/TEST/STATE':'b'})
        step={'condition':[{'parameter':'/TEST/STATE','operator':'gt','value':'a'}]}
        self.assertEqual(yc._run_verify_step(commander,step)['status'],'passed')

    def test_healthy_error_metric_needs_fresh_hk_without_new_errors(self):
        commander=MagicMock()
        commander.get_parameter_value.return_value={'value':0,'raw':{'acquisitionTime':'2026-10-06T00:00:01Z'}}
        step={'condition':[{'parameter':'/EPS/DEVICE_ERR_COUNT','operator':'gte','value':'0'}],'timeout':25}
        result=yc._run_verify_step(commander,step,require_fresh=True,
                    transaction_baselines={'/EPS/DEVICE_ERR_COUNT':0},
                    acquisition_baselines={'/EPS':'2026-10-06T00:00:00Z'})
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['actual']['/EPS/DEVICE_ERR_COUNT'],0)

    def test_fsw_counter_wrap_is_a_new_transaction(self):
        row={'value':65535,'raw':{'acquisitionTime':'2026-10-06T00:00:00Z'}}
        newer={'value':1,'raw':{'acquisitionTime':'2026-10-06T00:00:01Z'}}
        self.assertEqual(self.run_check([row,newer],{'/DEMO/DEVICE_COUNT':65535})['status'],'passed')

    def test_counter_reset_does_not_prove_responsiveness(self):
        row={'value':20,'raw':{'acquisitionTime':'2026-10-06T00:00:00Z'}}
        newer={'value':1,'raw':{'acquisitionTime':'2026-10-06T00:00:01Z'}}
        self.assertEqual(self.run_check([row,newer],{'/DEMO/DEVICE_COUNT':20})['status'],'failed')


class TestRadioRouting(unittest.TestCase):
    def test_native_ground_commands_are_executed_in_order_without_rest_link_control(self):
        commander = MagicMock()
        names = ['/SHIRE_GROUND/USE_RADIO_UPLINK', '/EPS/EPS_NOOP_CC',
                 '/SHIRE_GROUND/RESTORE_UPLINK']
        stack = {'steps': [{'type': 'command', 'name': name} for name in names]}
        stack['steps'][1]['comment'] = 'EPS RF probe via radio-out'
        with patch.object(yc, '_run_command_step', return_value={'status': 'passed'}) as command, \
             patch.object(yc.requests, 'post') as post:
            result = yc.run_stack(commander, stack, stack_name='RF probe')
        self.assertTrue(result['passed'])
        self.assertEqual([c.args[1]['name'] for c in command.call_args_list], names)
        post.assert_not_called()


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


class TestSimulatedVerifyTiming(unittest.TestCase):
    def test_server_clock_nanoseconds_are_recorded_in_seconds(self):
        commander=_commander_returning({'/SHIRE_SERVER/SIM_TIME_NS':1250000000})
        self.assertEqual(yc._sim_time(commander,'/SHIRE_SERVER/SIM_TIME_NS'),1.25)

    def test_verify_elapsed_uses_decoded_simulation_clock(self):
        commander = MagicMock()
        clock_samples = iter((75.0, 97.0))

        def get_parameter(name):
            if name == "/SIM_42_TRUTH/DYN_TIME":
                return {"value": next(clock_samples)}
            return {"value": 1}

        commander.get_parameter_value.side_effect = get_parameter
        stack = {"steps": [{"type": "verify", "condition": [
            {"parameter": "/ADCS/DEVICE_ENABLED", "operator": "eq", "value": "1"}]}]}
        result = yc.run_stack(commander, stack, stack_name="test",
                              sim_time_parameter="/SIM_42_TRUTH/DYN_TIME")
        self.assertTrue(result["passed"])
        self.assertEqual(result["steps"][0]["sim_elapsed_s"], 22.0)
        self.assertEqual(result["steps"][0]["sim_start_s"], 75.0)
        self.assertEqual(result["steps"][0]["sim_end_s"], 97.0)


if __name__ == "__main__":
    unittest.main()
