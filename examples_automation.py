#!/usr/bin/env python3
"""
Example automation script showing various YAMCS commanding patterns.

This demonstrates common use cases for commanding SHIRE via Python.
"""

import time
import sys

try:
    import requests
except ImportError:
    print("Error: 'requests' module required")
    print("Install with: pip install requests")
    sys.exit(1)


class ShireCommander:
    """Simple commander class for SHIRE spacecraft"""
    
    def __init__(self, yamcs_url="http://localhost:8090", instance="shire", processor="realtime"):
        self.base_url = f"{yamcs_url}/api/processors/{instance}/{processor}/commands"
        self.instance = instance
        
    def send_command(self, command_path, args=None):
        """Send a command to the spacecraft"""
        url = f"{self.base_url}{command_path}"
        
        payload = {}
        if args:
            payload['args'] = args
        
        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            result = response.json()
            print(f"✓ {command_path} - Command ID: {result.get('id')}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"✗ {command_path} - Error: {e}")
            return False


def example_1_basic_commands():
    """Example 1: Send basic commands"""
    print("\n" + "="*60)
    print("Example 1: Basic Commands")
    print("="*60)
    
    commander = ShireCommander()
    
    # Send NO-OP commands to each component
    print("\nSending NO-OP commands to verify connectivity:")
    commander.send_command('/CFS/CMD/CI_NOOP_CC')
    commander.send_command('/ADCS/ADCS_NOOP_CC')
    commander.send_command('/DEMO/DEMO_NOOP_CC')
    commander.send_command('/EPS/EPS_NOOP_CC')
    commander.send_command('/RADIO/RADIO_NOOP_CC')


def example_2_sequenced_commands():
    """Example 2: Send a sequence of commands with delays"""
    print("\n" + "="*60)
    print("Example 2: Sequenced Commands")
    print("="*60)
    
    commander = ShireCommander()
    
    print("\nEnabling telemetry output (setting radio to duplex mode):")
    commander.send_command('/RADIO/RADIO_CONFIG_CC', {'MODE': 'Duplex Mode'})
    
    time.sleep(1)
    
    print("\nResetting counters:")
    commander.send_command('/ADCS/ADCS_RST_COUNTERS_CC')
    time.sleep(0.5)
    commander.send_command('/DEMO/DEMO_RST_COUNTERS_CC')
    time.sleep(0.5)
    commander.send_command('/EPS/EPS_RST_COUNTERS_CC')
    time.sleep(0.5)
    commander.send_command('/RADIO/RADIO_RST_COUNTERS_CC')
    
    print("\nSequence complete!")


def example_3_commands_with_arguments():
    """Example 3: Send commands with arguments"""
    print("\n" + "="*60)
    print("Example 3: Commands with Arguments")
    print("="*60)
    
    commander = ShireCommander()
    
    # Example: Request ADCS housekeeping data
    print("\nRequesting ADCS housekeeping:")
    commander.send_command('/ADCS/ADCS_REQ_HK')
    
    # Example: Request DEMO housekeeping
    print("\nRequesting DEMO housekeeping:")
    commander.send_command('/DEMO/DEMO_REQ_HK')


def example_4_health_check():
    """Example 4: System health check routine"""
    print("\n" + "="*60)
    print("Example 4: Health Check Routine")
    print("="*60)
    
    commander = ShireCommander()
    
    components = [
        ('CI_LAB', '/CFS/CMD/CI_NOOP_CC'),
        ('ADCS', '/ADCS/ADCS_NOOP_CC'),
        ('DEMO', '/DEMO/DEMO_NOOP_CC'),
        ('EPS', '/EPS/EPS_NOOP_CC'),
        ('RADIO', '/RADIO/RADIO_NOOP_CC'),
    ]
    
    print("\nPerforming health check on all components:")
    results = []
    
    for name, cmd in components:
        success = commander.send_command(cmd)
        results.append((name, success))
        time.sleep(0.2)
    
    print("\nHealth Check Summary:")
    print("-" * 40)
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {name:12s} : {status}")
    
    all_passed = all(success for _, success in results)
    print("-" * 40)
    print(f"Overall: {'✓ ALL SYSTEMS GO' if all_passed else '✗ SOME FAILURES'}")


def example_5_automated_test():
    """Example 5: Automated test sequence"""
    print("\n" + "="*60)
    print("Example 5: Automated Test Sequence")
    print("="*60)
    
    commander = ShireCommander()
    
    test_steps = [
        ("Initialize", [
            ('/RADIO/RADIO_CONFIG_CC', {'MODE': 'Duplex Mode'}),
        ]),
        ("Reset Counters", [
            '/ADCS/ADCS_RST_COUNTERS_CC',
            '/DEMO/DEMO_RST_COUNTERS_CC',
            '/EPS/EPS_RST_COUNTERS_CC',
            '/RADIO/RADIO_RST_COUNTERS_CC',
        ]),
        ("Health Check", [
            '/ADCS/ADCS_NOOP_CC',
            '/DEMO/DEMO_NOOP_CC',
            '/EPS/EPS_NOOP_CC',
            '/RADIO/RADIO_NOOP_CC',
        ]),
    ]
    
    for step_name, commands in test_steps:
        print(f"\nTest Step: {step_name}")
        print("-" * 40)
        for cmd in commands:
            if isinstance(cmd, tuple):
                commander.send_command(cmd[0], cmd[1])
            else:
                commander.send_command(cmd)
            time.sleep(0.3)
    
    print("\n✓ Automated test sequence complete!")


def main():
    print("="*60)
    print("SHIRE YAMCS Commander - Example Automation Scripts")
    print("="*60)
    
    # Check if YAMCS is accessible
    try:
        response = requests.get("http://localhost:8090/api/", timeout=2)
        if response.status_code != 200:
            print("\n✗ YAMCS is not accessible")
            print("  Make sure SHIRE is running: make start")
            return 1
    except:
        print("\n✗ Cannot connect to YAMCS at http://localhost:8090")
        print("  Make sure SHIRE is running: make start")
        return 1
    
    print("\n✓ YAMCS connection verified")
    
    # Run examples
    try:
        example_1_basic_commands()
        time.sleep(2)
        
        example_2_sequenced_commands()
        time.sleep(2)
        
        example_3_commands_with_arguments()
        time.sleep(2)
        
        example_4_health_check()
        time.sleep(2)
        
        example_5_automated_test()
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 1
    
    print("\n" + "="*60)
    print("All examples completed!")
    print("="*60)
    print("\nNext steps:")
    print("  - Modify these examples for your use case")
    print("  - Check telemetry data in YAMCS UI: http://localhost:8090")
    print("  - Create your own automation scripts")
    print("="*60)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
