# SHIRE Ground Software (YAMCS)

This directory contains the YAMCS-based ground software for the SHIRE spacecraft project.

YAMCS provides telemetry and command (T&C) capabilities for monitoring and controlling the SHIRE spacecraft, which runs NASA's core Flight System (cFS).

This is a fork of the [Yamcs Quickstart](https://github.com/yamcs/quickstart), customized for SHIRE.


## Prerequisites

* Java 17+
  * For Ubuntu WSL:
    * `sudo apt install openjdk-17-jdk`
    * Add the following to your `~/.bashrc` file:
      * `export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`
      * `export PATH=$JAVA_HOME/bin:$PATH`
* Python 3.8+ (for commanding scripts)
* Linux x64/aarch64, macOS x64/aarch64, or Windows x64

A copy of Maven is also required, however this gets automatically downloaded and installed by using the `./mvnw` shell script as detailed below.


## Running Yamcs

Here are some commands to get things started:

Compile this project:

    ./mvnw compile

Start Yamcs on localhost:

    ./mvnw yamcs:run

Same as yamcs:run, but allows a debugger to attach at port 7896:

    ./mvnw yamcs:debug
    
Delete all generated outputs and start over:

    ./mvnw clean

This will also delete Yamcs data. Change the `dataDir` property in `yamcs.yaml` to another location on your file system if you don't want that.

**Note:** When running SHIRE via `make start` from the project root, YAMCS starts automatically within the docker compose environment and is accessible at `http://localhost:8090`.


## Python Commanding

### YAMCS Commander

A Python-based command-line tool for sending commands to SHIRE via YAMCS.

#### Installation

Install the required Python dependencies:

    pip install -r requirements-commander.txt

#### Usage

The commander defaults to interactive mode:

    ./yamcs_commander.py

Or explicitly start interactive mode:

    ./yamcs_commander.py --interactive

Send a single command:

    ./yamcs_commander.py --command /CFS/CMD/CFE_ES_NOOP

Send a command with arguments:

    ./yamcs_commander.py --command /CFS/CMD/CF_PLAYBACK_FILE --args "filename=/cf/test.bin,dest=1"

List all available commands:

    ./yamcs_commander.py --list

#### Interactive Mode

The interactive mode provides a command shell for exploring and sending commands:

```
yamcs> help                    # Show available commands
yamcs> list                    # Show command categories
yamcs> list cfs                # Show all CFS commands
yamcs> list adcs               # Show all ADCS commands
yamcs> send /CFS/CMD/CFE_ES_NOOP    # Send a command
yamcs> info /CFS/CMD/CFE_ES_NOOP    # Get command details
yamcs> quit                    # Exit
```

**Key Features:**
- Hierarchical command listing by category (CFS, ADCS, EPS, RADIO, DEMO, etc.)
- Command filtering and search
- Automatic pagination to fetch all available commands
- Support for both yamcs-client library and REST API
- Interactive help system

#### Command Categories

SHIRE commands are organized by subsystem:
- **CFS** - Core Flight System commands (CFE_ES, CFE_EVS, CFE_TBL, etc.)
- **ADCS** - Attitude Determination and Control System
- **EPS** - Electrical Power System
- **RADIO** - Radio/Communications commands
- **DEMO** - Demo component commands

Use `list <category>` to drill down into specific subsystems.

#### Configuration

Default connection settings:
- YAMCS URL: `http://localhost:8090`
- Instance: `shire`
- Processor: `realtime`

These can be overridden with command-line arguments:

    ./yamcs_commander.py --yamcs-url http://other-host:8090 --instance myinstance


## Telemetry

When running SHIRE via `make start`, telemetry data is automatically forwarded from the cFS instance to YAMCS over UDP.

The YAMCS web interface at `http://localhost:8090` provides:
- Real-time telemetry display
- Command history
- Event monitoring
- Parameter plots and visualization


## Telecommanding

Commands are sent from YAMCS to the SHIRE cFS instance via UDP. The spacecraft processes commands through the Command Ingest (CI) application.

You can send commands via:
1. **YAMCS Web UI** - Navigate to `http://localhost:8090` and use the commanding interface
2. **Python Commander** - Use `yamcs_commander.py` as described above
3. **Automation Scripts** - See `examples_automation.py` for scripting examples


## Development and Testing

### Automation Examples

See `examples_automation.py` for patterns including:
- Health check sequences
- Automated command sequences
- Event monitoring
- Batch commanding

## Bundling

Running through Maven is useful during development, but it is not recommended for production environments. Instead bundle up your Yamcs application in a tar.gz file:

    ./mvnw package


## Integration with SHIRE

YAMCS is integrated into the SHIRE docker compose stack:
- Service name: `shire-gsw`
- Web UI port: `8090` (exposed to host)
- Telemetry input: UDP packets from cFS TO (Telemetry Output)
- Command output: UDP packets to cFS CI (Command Ingest)

To start the full SHIRE system with YAMCS:

- cd /path/to/shire
- make
- make start

This will start cFS, Simulith, and YAMCS in a coordinated docker environment.
