#!/usr/bin/env python3
"""
YAMCS Commander - Python script to send commands to SHIRE via YAMCS

This script demonstrates commanding the spacecraft through YAMCS REST API.
Works with SHIRE running via 'make start'.

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
"""

import argparse
import os
import sys
import time
import requests
from typing import Dict, Optional

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
                
                # Wait for command to be acknowledged
                timeout = 10  # seconds
                start_time = time.time()
                ack_received = False
                
                while time.time() - start_time < timeout:
                    # Fetch updated command state
                    try:
                        # Get command history for this specific command
                        cmd_url = f"{self.rest_base}/archive/{self.instance}/commands/{issued_command.id}"
                        response = requests.get(cmd_url, timeout=2)
                        
                        if response.status_code == 200:
                            cmd_data = response.json()
                            acks = cmd_data.get('acknowledgments', [])
                            
                            if acks:
                                for ack in acks:
                                    ack_name = ack.get('name', 'Unknown')
                                    ack_status = ack.get('status', 'Unknown')
                                    ack_time = ack.get('time', 'N/A')
                                    print(f"  ✓ {ack_name}: {ack_status} at {ack_time}")
                                ack_received = True
                                break
                    except Exception:
                        # If REST API fails, try yamcs-client method
                        try:
                            cmd_history = self.client.get_command_history(
                                instance=self.instance,
                                limit=10
                            )
                            
                            for cmd in cmd_history:
                                if cmd.id == issued_command.id:
                                    acks = cmd.acknowledgments
                                    if acks:
                                        for ack in acks:
                                            ack_name = ack.name
                                            ack_status = ack.status
                                            ack_time = ack.time
                                            print(f"  ✓ {ack_name}: {ack_status} at {ack_time}")
                                        ack_received = True
                                    break
                        except Exception:
                            pass
                    
                    if ack_received:
                        break
                    
                    time.sleep(0.25)
                
                if not ack_received:
                    print("  ℹ No acknowledgment received within timeout (command may still execute)")
            
            return True
        except Exception as e:
            print(f"✗ Error sending command: {e}")
            return False

    def _send_via_rest(self, command_name: str, args: Optional[Dict]) -> bool:
        """Send command using REST API"""
        try:
            url = f"{self.rest_base}/processors/{self.instance}/{self.processor}/commands{command_name}"
            
            payload = {}
            if args:
                payload['assignment'] = [
                    {'name': k, 'value': v} for k, v in args.items()
                ]
            
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
    
    args = parser.parse_args()
    
    # Create commander
    commander = YAMCSCommander(args.yamcs_url, args.instance, args.processor)
    
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
