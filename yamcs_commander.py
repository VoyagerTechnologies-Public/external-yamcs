#!/usr/bin/env python3
"""
YAMCS Commander - Python script to send commands to SHIRE via YAMCS

This script demonstrates commanding the spacecraft through YAMCS REST API.
Works with SHIRE running via 'make start' or 'make scenario'.

Requirements:
    pip install yamcs-client requests

Usage:
    # Send a single command
    ./yamcs_commander.py --command TO_ENABLE_OUTPUT

    # Send command with arguments
    ./yamcs_commander.py --command CF_PLAYBACK_FILE --args "filename=/cf/test.bin,dest=1"

    # Interactive mode
    ./yamcs_commander.py --interactive

    # List available commands
    ./yamcs_commander.py --list

    # Run a YAMCS Stack (.ycs) file headlessly -- the same command/verify/check
    # sequence you'd otherwise run by hand in Procedures / Stacks in the web UI
    ./yamcs_commander.py --stack ../cfg/drm/gsw/procedures/CheckoutTest.ycs
"""

import argparse
import json
import operator as operator_module
import os
import pathlib
import sys
import time
from typing import Callable, Dict, List, Optional

import requests

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

try:
    from yamcs.client import YamcsClient
    YAMCS_CLIENT_AVAILABLE = True
except ImportError:
    YAMCS_CLIENT_AVAILABLE = False
    print("Warning: yamcs-client not installed. Falling back to REST API.")
    print("Install with: pip install yamcs-client")


class ParameterNotFoundError(RuntimeError):
    """The parameter doesn't exist in the MDB at all (HTTP 404) -- distinct
    from a real parameter that just hasn't produced a sample yet, which
    raises the plain RuntimeError instead and is worth retrying."""


class YAMCSCommander:
    """Interface to send commands to spacecraft via YAMCS"""

    def __init__(self, yamcs_url: str = "http://localhost:8090", 
                 instance: str = "shire", 
                 processor: str = "realtime"):
        """
        Initialize YAMCS commander

        Args:
            yamcs_url: Base URL for YAMCS server
            instance: YAMCS instance name
            processor: Processor name (usually 'realtime')
        """
        self.yamcs_url = yamcs_url
        self.instance = instance
        self.processor = processor
        self.rest_base = f"{yamcs_url}/api"
        
        if YAMCS_CLIENT_AVAILABLE:
            try:
                self.client = YamcsClient(yamcs_url)
                self.processor_client = self.client.get_processor(instance, processor)
                self.use_client = True
                print(f"✓ Connected to YAMCS at {yamcs_url}")
            except Exception as e:
                print(f"Warning: Could not initialize yamcs-client: {e}")
                self.use_client = False
        else:
            self.use_client = False

    def is_connected(self) -> bool:
        """Check if YAMCS is accessible"""
        try:
            response = requests.get(f"{self.rest_base}/", timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def list_commands(self) -> list:
        """List all available commands in the MDB"""
        try:
            # YAMCS API may paginate results, so we need to fetch all pages
            all_commands = []
            pos = 0
            limit = 1000  # Fetch in batches of 1000
            
            while True:
                url = f"{self.rest_base}/mdb/{self.instance}/commands?limit={limit}&pos={pos}"
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                
                data = response.json()
                commands = data.get('commands', [])
                
                if not commands:
                    break
                    
                all_commands.extend(commands)
                
                # Check if there are more commands to fetch
                total_size = data.get('totalSize', 0)
                if total_size > 0 and len(all_commands) >= total_size:
                    break
                    
                # If we got fewer than limit, we've reached the end
                if len(commands) < limit:
                    break
                    
                pos += limit
            
            return all_commands
        except Exception as e:
            print(f"Error listing commands: {e}")
            return []

    def send_command(self, command_name: str, args: Optional[Dict] = None, 
                    wait_for_ack: bool = True) -> bool:
        """
        Send a command to the spacecraft

        Args:
            command_name: Fully qualified command name (e.g., '/cFS/TO_ENABLE_OUTPUT')
            args: Dictionary of command arguments
            wait_for_ack: Wait for command acknowledgment

        Returns:
            True if command was sent successfully
        """
        if self.use_client:
            return self._send_via_client(command_name, args, wait_for_ack)
        else:
            return self._send_via_rest(command_name, args)

    def _send_via_client(self, command_name: str, args: Optional[Dict], 
                        wait_for_ack: bool) -> bool:
        """Send command using yamcs-client library"""
        try:
            print(f"Sending command: {command_name}")
            if args:
                print(f"  Arguments: {args}")
            
            # Issue command
            issued_command = self.processor_client.issue_command(command_name, args=args or {})
            print(f"✓ Command issued with ID: {issued_command.id}")
            
            if wait_for_ack:
                print("  Waiting for acknowledgment...")
                result = self.wait_for_acknowledgment(issued_command.id, None, wait_ms=10_000)
                if result["observed"]:
                    for ack_name, ack in result["acknowledgments"].items():
                        print(f"  ✓ {ack_name}: {ack.get('status')} at {ack.get('time')}")
                else:
                    print("  ℹ No acknowledgment received within timeout (command may still execute)")

            return True
        except Exception as e:
            print(f"✗ Error sending command: {e}")
            return False

    def _send_via_rest(self, command_name: str, args: Optional[Dict]) -> bool:
        """Send command using REST API"""
        try:
            url = f"{self.rest_base}/processors/{self.instance}/{self.processor}/commands{command_name}"

            # YAMCS 5.x's IssueCommandRequest takes a flat "args" object
            # (confirmed live against a running instance -- the older
            # "assignment": [{"name","value"}] list shape returns HTTP 400,
            # "Cannot find field: assignment").
            payload = {"args": args} if args else {}

            print(f"Sending command: {command_name}")
            if args:
                print(f"  Arguments: {args}")
            
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            
            result = response.json()
            print(f"✓ Command sent successfully")
            print(f"  Command ID: {result.get('id', 'N/A')}")
            print(f"  Generation Time: {result.get('generationTime', 'N/A')}")
            
            return True
        except requests.exceptions.RequestException as e:
            print(f"✗ Error sending command: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return False

    def get_command_info(self, command_name: str) -> Optional[Dict]:
        """Get detailed information about a command"""
        try:
            url = f"{self.rest_base}/mdb/{self.instance}/commands{command_name}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting command info: {e}")
            return None

    # ------------------------------------------------------------------
    # Stack-runner support (headless .ycs execution). Everything below is
    # REST-only, deliberately not going through the optional yamcs-client
    # fast path, so behavior doesn't change depending on whether that
    # package happens to be installed.
    # ------------------------------------------------------------------

    def issue_command(self, command_name: str, args: Optional[Dict] = None) -> Dict:
        """REST-only command issue. Unlike send_command(), returns the
        parsed response dict (its 'id' is needed for ack polling) and
        raises RuntimeError instead of printing and returning a bool."""
        url = f"{self.rest_base}/processors/{self.instance}/{self.processor}/commands{command_name}"
        payload = {"args": args} if args else {}
        try:
            response = requests.post(url, json=payload, timeout=5)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"POST {url} failed: {e}") from e
        if response.status_code >= 400:
            raise RuntimeError(
                f"POST {url} returned HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def get_command_acknowledgments(self, command_id: str) -> Dict[str, Dict[str, str]]:
        """Fetch and parse the named acknowledgments for a command from its
        archive history entry. YAMCS reports each acknowledgment as a pair
        of flat 'attr' entries, '<Name>_Status' and '<Name>_Time' -- there
        is no top-level 'acknowledgments' list in this API version
        (confirmed live against a running instance; an earlier version of
        this method assumed one). Returns {} if the command isn't in the
        archive yet or has no acknowledgments recorded."""
        url = f"{self.rest_base}/archive/{self.instance}/commands/{command_id}"
        try:
            response = requests.get(url, timeout=2)
        except requests.exceptions.RequestException:
            return {}
        if response.status_code != 200:
            return {}
        attrs = {a["name"]: a.get("value", {}) for a in response.json().get("attr", [])}
        acks: Dict[str, Dict[str, str]] = {}
        for name, value in attrs.items():
            if name.endswith("_Status"):
                acks.setdefault(name[: -len("_Status")], {})["status"] = value.get("stringValue")
            elif name.endswith("_Time"):
                acks.setdefault(name[: -len("_Time")], {})["time"] = value.get("stringValue")
        return acks

    def wait_for_acknowledgment(self, command_id: str, ack_name: Optional[str],
                                wait_ms: int) -> Dict[str, object]:
        """Poll until `ack_name` (or, if None, any acknowledgment) appears
        for `command_id`, up to wait_ms milliseconds. Never raises -- a
        timeout is a normal outcome to report, not a connectivity error."""
        deadline = time.time() + wait_ms / 1000.0
        while True:
            acks = self.get_command_acknowledgments(command_id)
            observed = (ack_name in acks) if ack_name is not None else bool(acks)
            if observed:
                relevant = {ack_name: acks[ack_name]} if ack_name is not None else acks
                return {"observed": True,
                        "ok": all(a.get("status") == "OK" for a in relevant.values()),
                        "acknowledgments": acks}
            if time.time() >= deadline:
                return {"observed": False, "ok": False, "acknowledgments": acks}
            time.sleep(0.25)

    def get_parameter_value(self, parameter_name: str) -> Dict[str, object]:
        """GET the current/latest value of a parameter in this processor.
        Confirmed live: {rest_base}/processors/{instance}/{processor}/parameters{name}
        returns an 'engValue' object shaped {"type": <TYPE>, "<type>Value": <value>}
        (e.g. {"type": "FLOAT", "floatValue": 0.0}) -- the value key name
        varies by type, so it's picked generically as "whichever key in
        engValue isn't 'type'" rather than hardcoding a type list.

        Raises ParameterNotFoundError (confirmed live: HTTP 404, "No
        parameter named ...") for a misspelled/nonexistent parameter --
        retrying that will never help. Raises the plain RuntimeError for a
        real parameter that simply hasn't produced its first sample yet
        (HTTP 200, no 'engValue', confirmed live right after boot) --
        callers should retry that one within their own timeout."""
        url = f"{self.rest_base}/processors/{self.instance}/{self.processor}/parameters{parameter_name}"
        try:
            response = requests.get(url, timeout=5)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"GET {url} failed: {e}") from e
        if response.status_code == 404:
            raise ParameterNotFoundError(f"GET {url}: {response.text[:500]}")
        if response.status_code != 200:
            raise RuntimeError(
                f"GET {url} returned HTTP {response.status_code}: {response.text[:500]}")
        try:
            body = response.json()
        except ValueError as e:
            raise RuntimeError(f"GET {url} returned non-JSON body: {response.text[:500]}") from e
        eng_value = body.get("engValue")
        if not eng_value:
            raise RuntimeError(
                f"GET {url}: parameter has no engValue yet "
                f"(acquisitionStatus={body.get('acquisitionStatus')!r}): {json.dumps(body)[:500]}")
        value_keys = [k for k in eng_value if k != "type"]
        if not value_keys:
            raise RuntimeError(f"GET {url}: engValue has no typed value field: {eng_value}")
        return {"value": eng_value[value_keys[0]], "type": eng_value.get("type"), "raw": body}

    def interactive_mode(self):
        """Run interactive command interface"""
        # Setup readline for command history
        history_file = os.path.expanduser('~/.yamcs_commander_history')
        
        if READLINE_AVAILABLE:
            # Configure readline
            readline.parse_and_bind('tab: complete')
            
            # Load history from file if it exists
            if os.path.exists(history_file):
                try:
                    readline.read_history_file(history_file)
                except Exception:
                    pass
            
            # Set history length
            readline.set_history_length(1000)
        
        def show_help():
            print("\nAvailable commands:")
            print("  list                    - List command categories")
            print("  list <filter>           - List commands matching filter (e.g., 'list adcs')")
            print("  send <command> [args]   - Send a command with optional arguments")
            print("                            Example: send /RADIO/RADIO_CONFIG_CC MODE=\"Duplex Mode\"")
            print("  info <command>          - Get command information")
            print("  help                    - Show this help message")
            print("  quit/exit               - Exit interactive mode")
        
        print("\n" + "="*60)
        print("YAMCS Commander - Interactive Mode")
        print("="*60)
        if READLINE_AVAILABLE:
            print("Tip: Use arrows to navigate command history")
        show_help()
        print("="*60 + "\n")

        while True:
            try:
                user_input = input("yamcs> ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("Exiting...")
                    break
                
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                
                if cmd == 'help' or cmd == '?':
                    show_help()
                
                elif cmd == 'list':
                    commands = self.list_commands()
                    
                    # Group commands by category (first part of qualified name)
                    categories = {}
                    for cmd_info in commands:
                        name = cmd_info.get('qualifiedName', '')
                        # Extract category (e.g., /CFS/CMD/... -> CFS)
                        name_parts = name.strip('/').split('/')
                        category = name_parts[0] if name_parts else 'Unknown'
                        if category not in categories:
                            categories[category] = []
                        categories[category].append(cmd_info)
                    
                    # Check if a filter was provided
                    filter_text = parts[1].lower() if len(parts) > 1 else None
                    
                    if filter_text:
                        # Check if filter matches a category name
                        matching_category = None
                        for cat_name in categories.keys():
                            if cat_name.lower() == filter_text:
                                matching_category = cat_name
                                break
                        
                        if matching_category:
                            # Show all commands in this category
                            cmd_list = categories[matching_category]
                            print(f"\nCommands in category '{matching_category}' ({len(cmd_list)}):")
                            for i, command in enumerate(cmd_list, 1):
                                qualified_name = command.get('qualifiedName', 'Unknown')
                                short_desc = command.get('shortDescription', '')
                                print(f"  {i:3d}. {qualified_name}")
                                if short_desc:
                                    print(f"       {short_desc}")
                        else:
                            # Filter commands containing the filter text
                            filtered = [c for c in commands 
                                       if filter_text in c.get('qualifiedName', '').lower()]
                            print(f"\nCommands matching '{filter_text}' ({len(filtered)}):")
                            for i, command in enumerate(filtered, 1):
                                qualified_name = command.get('qualifiedName', 'Unknown')
                                short_desc = command.get('shortDescription', '')
                                print(f"  {i:3d}. {qualified_name}")
                                if short_desc:
                                    print(f"       {short_desc}")
                            if not filtered:
                                print(f"  No commands found matching '{filter_text}'")
                    else:
                        # Show categories overview
                        print(f"\nCommand Categories ({len(categories)} categories, {len(commands)} total commands):")
                        print("\nUse 'list <category>' to see all commands in a category")
                        print("Example: list cfs, list adcs, list eps\n")
                        
                        for category in sorted(categories.keys()):
                            cmd_list = categories[category]
                            print(f"  {category:15s} ({len(cmd_list):3d} commands)")
                
                elif cmd == 'send' and len(parts) > 1:
                    # Parse command and arguments
                    # Format: send /COMMAND/PATH ARG1=val1 ARG2="value 2"
                    send_parts = parts[1].split()
                    if not send_parts:
                        print("Error: No command specified")
                        continue
                    
                    command_name = send_parts[0]
                    cmd_args = {}
                    
                    # Parse arguments if provided
                    if len(send_parts) > 1:
                        for arg_str in send_parts[1:]:
                            if '=' in arg_str:
                                key, value = arg_str.split('=', 1)
                                # Strip quotes if present
                                value = value.strip('"').strip("'")
                                
                                # Try to convert to int if it looks like a number
                                try:
                                    if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                                        value = int(value)
                                    elif value.replace('.', '', 1).replace('-', '', 1).isdigit():
                                        value = float(value)
                                except (ValueError, AttributeError):
                                    pass  # Keep as string
                                
                                cmd_args[key.strip()] = value
                            else:
                                print(f"Warning: Ignoring invalid argument format: {arg_str}")
                    
                    self.send_command(command_name, cmd_args if cmd_args else None, wait_for_ack=False)
                
                elif cmd == 'info' and len(parts) > 1:
                    command_name = parts[1]
                    info = self.get_command_info(command_name)
                    if info:
                        print(f"\nCommand: {info.get('qualifiedName', 'Unknown')}")
                        print(f"Description: {info.get('shortDescription', 'N/A')}")
                        if 'argument' in info:
                            print("Arguments:")
                            for arg in info['argument']:
                                print(f"  - {arg.get('name')}: {arg.get('type', {}).get('engType', 'unknown')}")
                
                else:
                    print("Unknown command or invalid syntax")
            
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
        
        # Save history on exit
        if READLINE_AVAILABLE:
            try:
                readline.write_history_file(history_file)
            except Exception:
                pass


# ----------------------------------------------------------------------
# Headless ".ycs" stack execution -- replaces manually opening a stack in
# Procedures / Stacks in the YAMCS web UI and clicking through it (schema:
# https://yamcs.org/schema/stack.schema.json). Confirmed step shapes by
# reading cfg/drm/gsw/procedures/CheckoutTest.ycs and
# comp/adcs/gsw/procedures/AdcsComponent.ycs directly.
# ----------------------------------------------------------------------

DEFAULT_VERIFY_TIMEOUT_MS = 30_000
DEFAULT_ADVANCEMENT_WAIT_MS = 5_000  # only used if a command step has no
                                      # advancement at step or stack level

STACK_OPERATORS: Dict[str, Callable[[object, object], bool]] = {
    "eq": operator_module.eq, "gt": operator_module.gt, "lt": operator_module.lt,
    "gte": operator_module.ge, "lte": operator_module.le, "ne": operator_module.ne,
}


def load_stack(path: pathlib.Path) -> Dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "steps" not in data:
        raise ValueError(f"{path}: missing top-level 'steps' array (not a .ycs stack?)")
    return data


def _coerce_expected(expected_raw: str, actual_value: object) -> object:
    """condition['value'] is always a JSON string, even for numeric
    compares (confirmed live). Coerce to float only when the live
    parameter value is itself numeric."""
    if isinstance(actual_value, (int, float)) and not isinstance(actual_value, bool):
        try:
            return float(expected_raw)
        except ValueError:
            return expected_raw
    return expected_raw


def _run_command_step(commander: YAMCSCommander, step: Dict,
                      stack_advancement: Optional[Dict]) -> Dict:
    name = step["name"]
    args = {a["name"]: a["value"] for a in step.get("arguments", [])} or None
    try:
        response = commander.issue_command(name, args)
    except RuntimeError as e:
        return {"status": "failed", "expected": "command accepted", "detail": str(e)}
    command_id = response.get("id")
    advancement = step.get("advancement", stack_advancement)
    if advancement and command_id:
        ack_name = advancement.get("acknowledgment")
        wait_ms = advancement.get("wait", DEFAULT_ADVANCEMENT_WAIT_MS)
        ack = commander.wait_for_acknowledgment(command_id, ack_name, wait_ms)
        if not (ack["observed"] and ack["ok"]):
            return {"status": "failed",
                    "expected": f"acknowledgment {ack_name!r} (OK) within {wait_ms}ms",
                    "actual": ack["acknowledgments"]}
    return {"status": "passed", "expected": "command accepted", "actual": command_id}


def _run_verify_step(commander: YAMCSCommander, step: Dict) -> Dict:
    conditions = step.get("condition", [])
    timeout_s = step.get("timeout", DEFAULT_VERIFY_TIMEOUT_MS) / 1000.0
    deadline = time.time() + timeout_s
    last_actual: Dict[str, object] = {}
    last_detail: Optional[str] = None
    while True:
        all_ok = True
        last_actual = {}
        last_detail = None
        for cond in conditions:
            param, op_name, expected_raw = cond["parameter"], cond["operator"], cond["value"]
            comparator = STACK_OPERATORS.get(op_name)
            if comparator is None:
                return {"status": "failed", "expected": conditions,
                        "detail": f"unsupported operator {op_name!r}"}
            try:
                observed = commander.get_parameter_value(param)
            except ParameterNotFoundError as e:
                # Misspelled/nonexistent parameter: retrying won't help.
                return {"status": "failed", "expected": conditions, "detail": str(e)}
            except RuntimeError as e:
                # Real parameter, no sample yet: keep polling like a
                # not-yet-matching value would, until this step's timeout.
                all_ok = False
                last_actual[param] = None
                last_detail = str(e)
                continue
            actual = observed["value"]
            last_actual[param] = actual
            all_ok = all_ok and comparator(actual, _coerce_expected(expected_raw, actual))
        if all_ok:
            return {"status": "passed", "expected": conditions, "actual": last_actual}
        if time.time() >= deadline:
            return {"status": "failed", "expected": conditions,
                    "actual": last_actual, "detail": last_detail}
        time.sleep(0.5)


def _run_check_step(commander: YAMCSCommander, step: Dict) -> Dict:
    """'check' steps are display-only per the stack schema -- they never
    fail the stack, even if a parameter can't be read (e.g. never
    generated yet); the read error is recorded for visibility instead."""
    values: Dict[str, object] = {}
    errors: List[str] = []
    for p in step.get("parameters", []):
        try:
            values[p["parameter"]] = commander.get_parameter_value(p["parameter"])["value"]
        except RuntimeError as e:
            errors.append(str(e))
    return {"status": "passed", "actual": values, "detail": "; ".join(errors) or None}


def run_stack(commander: YAMCSCommander, stack: Dict, *, stack_name: str) -> Dict:
    """Runs every step of a loaded .ycs stack to completion (never stops
    at the first failure -- matches how the YAMCS web UI already shows
    every step's status as it goes) and returns a structured result.

    Prints a line before and after each step (flushed immediately), not
    just a final summary: a "verify" step can legitimately poll for up to
    its full timeout (seconds to a couple of minutes), and a silent stack
    runner mid-poll looks identical to a hung one. The caller
    (cfg/shire-scenario.py's run_scheduled_verify_stacks) streams this
    process's stdout live for exactly that reason."""
    stack_advancement = stack.get("advancement")
    steps = stack.get("steps", [])
    results: List[Dict] = []
    print(f"[stack] {stack_name}: {len(steps)} step(s)", flush=True)
    for index, step in enumerate(steps):
        step_type = step.get("type")
        step_label = step.get("name") or step.get("comment") or step_type
        print(f"[stack] {index + 1}/{len(steps)} {step_type} {step_label}: starting", flush=True)
        started = time.monotonic()
        if step_type == "command":
            outcome = _run_command_step(commander, step, stack_advancement)
        elif step_type == "verify":
            outcome = _run_verify_step(commander, step)
        elif step_type == "check":
            outcome = _run_check_step(commander, step)
        elif step_type == "text":
            outcome = {"status": "passed", "actual": step.get("text")}
        else:
            outcome = {"status": "failed", "detail": f"unknown step type {step_type!r}"}
        elapsed_s = round(time.monotonic() - started, 3)
        print(f"[stack] {index + 1}/{len(steps)} {step_type} {step_label}: "
              f"{outcome['status']} ({elapsed_s}s)", flush=True)
        results.append({
            "index": index, "type": step_type,
            "name": step.get("name") or step.get("comment"),
            "status": outcome["status"],
            "expected": outcome.get("expected"), "actual": outcome.get("actual"),
            "detail": outcome.get("detail"),
            "elapsed_s": elapsed_s,
        })
    failures = [r for r in results if r["status"] == "failed"]
    return {"stack": stack_name, "passed": not failures,
            "step_count": len(results), "steps": results, "failures": failures}


def parse_args_string(args_string: str) -> Dict:
    """Parse command arguments from string format 'key1=val1,key2=val2'"""
    if not args_string:
        return {}
    
    args = {}
    for pair in args_string.split(','):
        if '=' in pair:
            key, value = pair.split('=', 1)
            args[key.strip()] = value.strip()
    return args


def main():
    parser = argparse.ArgumentParser(
        description='Send commands to SHIRE spacecraft via YAMCS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all available commands
  %(prog)s --list

  # Send a simple command
  %(prog)s --command /cFS/TO_ENABLE_OUTPUT

  # Send command with arguments
  %(prog)s --command /cFS/CF_PLAYBACK_FILE --args "filename=/cf/test.bin,dest=1"

  # Interactive mode
  %(prog)s --interactive
        """
    )
    
    parser.add_argument('--yamcs-url', default='http://localhost:8090',
                       help='YAMCS server URL (default: http://localhost:8090)')
    parser.add_argument('--instance', default='shire',
                       help='YAMCS instance name (default: shire)')
    parser.add_argument('--processor', default='realtime',
                       help='Processor name (default: realtime)')
    
    parser.add_argument('--command', '-c',
                       help='Command to send (e.g., /cFS/TO_ENABLE_OUTPUT)')
    parser.add_argument('--args', '-a',
                       help='Command arguments in format: key1=val1,key2=val2')
    parser.add_argument('--list', '-l', action='store_true',
                       help='List all available commands')
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='Start interactive command mode')
    parser.add_argument('--stack', type=pathlib.Path,
                       help='Run a YAMCS Stack (.ycs) file headlessly and exit 0/1 on pass/fail')
    parser.add_argument('--report', type=pathlib.Path,
                       help='With --stack: write the JSON step-by-step result here')
    parser.add_argument('--connect-timeout-s', type=float, default=30.0,
                       help='With --stack: seconds to wait for YAMCS to become reachable '
                            '(default: 30)')

    args = parser.parse_args()

    # Create commander
    commander = YAMCSCommander(args.yamcs_url, args.instance, args.processor)

    if args.stack:
        deadline = time.time() + args.connect_timeout_s
        while not commander.is_connected():
            if time.time() >= deadline:
                print(f"✗ Cannot connect to YAMCS at {args.yamcs_url} "
                      f"within {args.connect_timeout_s}s", file=sys.stderr)
                return 1
            time.sleep(1)
        stack = load_stack(args.stack)
        result = run_stack(commander, stack, stack_name=str(args.stack))
        text = json.dumps(result, indent=2, sort_keys=True)
        if args.report:
            args.report.write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"[yamcs-stack] {'PASS' if result['passed'] else 'FAIL'}: "
              f"{len(result['failures'])}/{result['step_count']} step(s) failed")
        return 0 if result["passed"] else 1

    # Check connection
    if not commander.is_connected():
        print(f"✗ Cannot connect to YAMCS at {args.yamcs_url}")
        print("  Make sure SHIRE is running: make start")
        return 1

    # Execute requested action
    if args.list:
        commands = commander.list_commands()
        print(f"\nAvailable commands ({len(commands)}):")
        for i, command in enumerate(commands, 1):
            qualified_name = command.get('qualifiedName', 'Unknown')
            short_desc = command.get('shortDescription', '')
            print(f"  {i:3d}. {qualified_name}")
            if short_desc:
                print(f"       {short_desc}")
        return 0
    
    elif args.interactive:
        commander.interactive_mode()
        return 0
    
    elif args.command:
        cmd_args = parse_args_string(args.args) if args.args else None
        success = commander.send_command(args.command, cmd_args)
        return 0 if success else 1
    
    else:
        # Default to interactive mode
        commander.interactive_mode()
        return 0


if __name__ == '__main__':
    sys.exit(main())
