# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Write a program based on the Unix philosophy
* Write programs that do one thing and do it well.
* Write programs to work together.
* Write programs to handle text streams, because that is a universal interface.

# Interaction contract
- If requirements are ambiguous or underspecified, stop and ask 1–3 targeted questions before proceeding.
- Before making any irreversible change (deletes, migrations, dependency upgrades, infra changes), ask for explicit confirmation.
- Never assume environment details (OS, shell, package manager, project conventions). Ask or infer only from repo evidence.
- Start each task by restating: Goal, Non-goals, Constraints, Success criteria (brief).
- When multiple approaches exist, present 2 options with tradeoffs, then ask which to take.

## Notice

Separate functions into separate files by type, and do not recreate existing functions in the execution script. If you need to edit them, edit the existing function and check that the modifications have been made.
Make functions as flexible as possible by using variables.


## Project Overview

CeforeEmu is a network emulator based on Mininet for testing Cefore (Content-Centric Networking framework) deployments. It creates virtual network topologies with virtual hosts running Cefore daemons (cefnetd) to simulate content distribution scenarios.

**External Dependencies:**
- Cefore must be installed on Ubuntu 22.04
- Mininet version 2.3.0 must be installed
- All scripts require root privileges (sudo)

## Project Structure

```
cefore-emu/
├── src/                           # Main source code
│   ├── __init__.py
│   ├── __main__.py                # python -m src entry point
│   ├── cli/                       # CLI interface
│   │   ├── __init__.py
│   │   ├── main.py                # Subcommand dispatcher
│   │   └── args.py                # Argument parser definitions
│   ├── core/                      # Core logic and algorithms
│   │   ├── __init__.py
│   │   ├── config/                # Configuration utilities
│   │   │   ├── __init__.py
│   │   │   ├── loader.py          # JSON/YAML config loader
│   │   │   └── priority_resolver.py  # Config priority resolution
│   │   ├── fib.py                 # FIB route computation
│   │   ├── flap_state.py          # Host flap state tracking
│   │   ├── graph.py               # Graph algorithms (Dijkstra, k-center)
│   │   ├── paths.py               # Output path resolution
│   │   ├── roles.py               # Node role assignment
│   │   └── tee.py                 # Tee stdout/stderr to file
│   ├── log/                       # Log parsing and CSV summarization
│   │   ├── __init__.py            # Exports
│   │   ├── filename.py            # Filename pattern → metadata extraction
│   │   ├── parser.py              # Log text → dict parser
│   │   ├── plotter.py             # Log data plotting
│   │   ├── summarizer.py          # Directory walk + CSV output
│   │   └── cli.py                 # argparse CLI
│   ├── runtime/                   # Runtime operations
│   │   ├── __init__.py
│   │   ├── bandwidth.py           # Link bandwidth control
│   │   ├── base.py                # Base runtime utilities
│   │   ├── bridge.py              # Linux bridge & root NS bridging
│   │   ├── cache_manager.py       # Cache manager operations
│   │   ├── cefore.py              # Cefore daemon start/stop/wait
│   │   ├── external_net.py        # External network mesh scenario
│   │   ├── failure_manager.py     # Host failure simulation
│   │   ├── links.py               # Link state control (up/down)
│   │   ├── monitoring.py          # Periodic status collection
│   │   ├── net_config.py          # IP address & FIB application
│   │   ├── scheduler.py           # Timed event scheduler
│   │   ├── template.py            # Host directory template management
│   │   ├── topo.py                # Mininet Topo subclass (MeshTopo)
│   │   └── viz.py                 # Topology visualization & PNG output
│   └── scenarios/                 # Scenario implementations
│       ├── __init__.py
│       ├── base.py                # Shared scenario utilities
│       ├── linear.py              # Linear topology scenario
│       ├── mesh.py                # Mesh topology scenario
│       └── disaster.py            # Mesh with disaster simulation
│
├── config/                        # Configuration
│   ├── templates/                 # Host templates
│   │   ├── h0/                    # Consumer template (CS_MODE=0)
│   │   ├── h1/                    # Router template (CS_MODE=2)
│   │   └── h2/                    # Publisher template (CS_MODE=1)
│   └── examples/                  # Example configurations
│       ├── example.yaml           # Full config reference (all args, commented)
│       ├── example.json           # Same config in JSON format
│       └── auto_experiment.yaml   # Auto-experiment configuration
│
├── doc/                           # Design documents
│   ├── autotest_plan_reviewed.md  # Autotest implementation plan
│   ├── cefore_emu_autotest_spec.md # Autotest specification
│   └── branch-retirement-feature-test.md
├── tools/
│   └── autotest/                  # Batch experiment runner
│
├── sample-putfile                 # Test data (root exception)
├── buffer.sh                      # UDP buffer configuration (root exception)
├── pyproject.toml                 # Package configuration
└── CLAUDE.md                      # This file
```

## Running Topology Scripts

**Linear topology:**
```bash
sudo python3 -m src linear --hosts 7
```

**Mesh topology:**
```bash
sudo python3 -m src mesh --hosts 8 --switches 12 --k 3 --seed 42
```

**Disaster topology with host failures:**
```bash
sudo python3 -m src disaster --hosts 10 --switches 15 --seed 42 \
    --down-interval 30 --down-duration 10 --down-count 2
```

**Using JSON/YAML configuration:**
```bash
sudo python3 -m src disaster --config config/examples/example.yaml
```

If installed via `uv` / `pip install -e .`, the `ceforeemu` command is also available:
```bash
sudo ceforeemu disaster --config config/examples/example.yaml
```

**Exiting Mininet:**
```
mininet> exit
```

**Network buffer configuration:**
```bash
./buffer.sh  # Increases UDP buffer sizes for Cefore
```

## Architecture

### Topology Scripts Structure

All topology scripts follow a common pattern:

1. **Topology Definition** - Mininet Topo subclass defines network structure
2. **IP Address Assignment** - Each link gets a /24 subnet (192.168.X.Y)
3. **Cefore Daemon Startup** - Start csmgrd (cache managers) and cefnetd (forwarding daemons)
4. **FIB Configuration** - Set forwarding rules using `cefroute add`
5. **Content Operations** - Publisher runs `cefputfile`, consumer runs `cefgetfile`
6. **Cleanup** - Stop daemons and remove temporary host directories

### Node Role Assignment

- **Consumer** (h0): Requests content via `cefgetfile`
- **Router** (h1, odd-numbered hosts): Forwards interests/content, runs cache manager (csmgrd)
- **Publisher** (h2, last host): Stores and serves content via `cefputfile`

### Host Configuration Templates

Templates are located in `config/templates/`:

- `h0/` - Consumer template (CS_MODE=0, no caching)
- `h1/` - Router template (CS_MODE=2, external cache manager)
- `h2/` - Publisher template (CS_MODE=1, local cache mode)

For topologies with >3 hosts, additional directories (h3, h4, ...) are generated dynamically by copying templates. Dynamic directories are cleaned up after script completion via `cleanup_node_dirs()`.

**Configuration files per host:**
- `cefnetd.conf` - Forwarding daemon config (includes LOCAL_SOCK_ID)
- `cefnetd.fib` - Static forwarding table
- `csmgrd.conf` - Cache manager config
- `conpubd.conf` - Publisher daemon config
- `plugin.conf` - Plugin configuration
- `cefnetd.key` - Key configuration
- `default-private-key`, `default-public-key` - Cryptographic keys (sensitive)

### Key Functions

**IP Address Assignment:**
- Linear topologies: Sequential /24 subnets (192.168.0.x, 192.168.1.x, ...)
- Mesh topologies: One /24 per link, host ID determines last octet

**FIB Configuration:**
- Linear: Forward all interests toward publisher (next hop in line)
- Mesh: Uses per-source Dijkstra for efficient multipath routing
  - `dijkstra_all()`: Computes shortest distances from a source to all destinations
  - For each source-destination pair, selects k best neighbors based on their precomputed distance to destination
  - `shortest_path()`: Dijkstra's algorithm with edge/node banning support (used for constrained pathfinding)
  - `k_shortest_paths()`: Yen's algorithm for finding k alternate paths (available but not used in main FIB setup)
  - `set_fib()`: Sets FIB entries for all destinations with default URI pattern `ccnx:/test/exampleN`
  - `set_fib_for_uris()`: Sets FIB entries for specific URI-to-publisher mappings (used with publication events)

**Dynamic Configuration:**
- `update_local_sock_id()`: Modifies LOCAL_SOCK_ID in config files to avoid socket conflicts
- `ensure_node_dirs()`: Creates host directories from templates based on role heuristics
- `select_template()`: Determines which template (h0/h1/h2) to use for each host index

**Content Operations (exported from `src/runtime`):**
- `run_cefputfile()`: Publish content via cefputfile with configurable options
- `run_cefgetfile()`: Retrieve content via cefgetfile with configurable options
- `run_cefpubfile()`: Publish content via cefpubfile (pub/sub model, returns a CommandHandle)
- `start_cefsubfile()`: Subscribe to content via cefsubfile (pub/sub model, returns a CommandHandle)

**Status/Info Commands:**
- `run_csmgrstatus()`: Query cache manager status via csmgrstatus

**FIB Route Management:**
- `cefroute_del()`: Delete a FIB entry via `cefroute del`
- `cefroute_enable()`: Enable a FIB entry via `cefroute enable`

### Mesh Topology Features

The mesh topologies (`src/scenarios/mesh.py`, `src/scenarios/disaster.py`) implement advanced features:

- **Multipath routing**: k-shortest paths per destination for redundancy
- **Link control**: `link_up()` and `link_down()` functions to simulate failures
- **Topology visualization**: `print_mesh_links()` renders ASCII tree view showing each host's connectivity
- **Status inspection**: `run_cefstatus()` to view FIB state
- **Deterministic generation**: `--seed` parameter for reproducible topologies
- **Publisher-aware linking**: First link always connects to publisher for guaranteed connectivity
- **PNG output**: `render_topology_png()` generates topology visualization images

### Disaster Topology Features

The disaster topology (`src/scenarios/disaster.py`) adds:

**Host Failure Simulation:**
```bash
--down-interval <sec>    # Interval between down/up cycles
--down-duration <sec>    # Time to keep hosts down
--down-count <n>         # Number of hosts to down per cycle
--down-stagger <sec>     # Offset between individual host downs
--down-exclude <ids>     # Host IDs to exclude (comma-separated)
```

**Bandwidth Control:**
```bash
--bw nodeA,nodeB,mbps    # Set link bandwidth (repeatable)
```

**External Interface:**
```bash
--ext host,ifname,ip[,mtu]   # Attach external interface to host (ip required, CIDR form; DHCP unsupported)
```

**Addressing for External Connectivity:**
When connecting to external physical Cefore devices via `ext`/`bridges`, the default `192.168.0.0/16` conflicts with common LAN addressing. In Class C Ethernet environments, packets may be dropped (no route on external device) or misrouted to wrong hosts sharing the same subnet.

Use `addressing.network_cidr` to select a non-conflicting /16:

| Address Range | Recommendation | Rationale |
|---------------|----------------|-----------|
| `100.64.0.0/16` | Primary | RFC 6598 CGNAT space — virtually never used on LANs |
| `172.20.0.0/16` | Fallback | RFC 1918 Class B — less common than 192.168.x.x but used in some enterprise LANs |

External devices must also add a static route to the Mininet internal range:
```bash
ip route add 100.64.0.0/16 via <bridge_root_ns_ip>
```

**Root Namespace Bridging (runtime/bridge.py - BridgeManager):**
Connects Mininet switches to the root namespace for cross-VM communication. BridgeManager handles veth pairs, IP routes, forwarding, NAT, and cleanup.

**Autotest Mode (--no-cli + --results-json):**
```bash
sudo ceforeemu disaster --config config/examples/example.yaml --no-cli --duration 120 --results-json results.json
```
Runs experiment without interactive CLI and saves structured results to JSON.

Autotest uses one absolute event clock from experiment start across seed and
evaluation schedulers. It preserves `put -> warmup -> failure -> eval`
ordering; evaluation events already overdue after warmup run immediately and
log their scheduled time, actual time, and delay. A `put` event with `repeat`
is invalid in autotest. `duration` measures observation time after the failure
phase starts; when no evaluation event exists and `duration` is zero, the
failure phase is skipped with a warning.

**Cache Configuration:**
```bash
--cache-count <n>                # Number of cache nodes (0 = down-count + 1)
--cache-default-rct-ms <ms>      # Override CACHE_DEFAULT_RCT for cache nodes
```

**Pub/Sub Model:**
Events with `type: pubsub_pub` use `cefpubfile`; events with
`type: pubsub_sub` use `cefsubfile`.

- A `pubsub_sub` result is stored under an **output directory** (not a predictable file). `cefsubfile -f` requires a directory, and creates `RNP0x<hex>.out` files inside it with session-derived names that cannot be predicted in advance.
- Success detection for pubsub uses exit code + presence of a non-empty `RNP0x*.out` file in the output directory (no log text matching).
- All cefore command wrappers redirect stdout **and stderr** to the same log file (`> logfile 2>&1`). This ensures failure diagnostics from stderr are always captured.
- `cefpubfile` log names are unique per cycle/index: `cefpubfile_seed{seed}_downhosts{...}_phase{phase}_cycle{N}_idx{N}_h{host}.log` — same format as `cefsubfile` logs.

**Event Scheduler (`src/runtime/scheduler.py`):**
Timed events configured via `events` key in YAML/JSON. Events execute in a background thread.
```yaml
events:
  - {at: 15, type: link_down, nodes: [1, 2]}
  - {at: 25, type: link_up, nodes: [1, 2]}
  - {at: 30, type: fib_del, host: 3, prefix: "ccnx:/test/sample", next_hop: "192.168.1.1"}
```
Supported types: `link_down`, `link_up`, `fib_add`, `fib_del`, `fib_enable`.

**Monitoring (`src/runtime/monitoring.py`):**
Periodic status collection configured via `monitoring` key in YAML/JSON.
```yaml
monitoring:
  interval: 5
  output_json: "monitor.json"
  output_csv: "monitor.csv"
  targets:
    - {type: cefstatus, hosts: "all"}
    - {type: csmgrstatus, hosts: "cache"}
```
Supported types: `cefstatus`, `csmgrstatus`. Hosts can be `"all"`, `"cache"`, or a list of IDs.

**JSON/YAML Configuration:**

Configuration files support both JSON and YAML formats (YAML requires `pyyaml`).

Basic JSON example with multiple publishers:
```json
{
  "hosts": 10,
  "switches": 15,
  "seed": 42,
  "events": [
    {"at": 0, "type": "put", "host": 9, "uri": "ccnx:/test/video1", "file": "./video.bin", "rate": 10, "expiry": 5000, "cache_time": 5000},
    {"at": 0, "type": "put", "host": 7, "uri": "ccnx:/test/data1", "file": "./data.bin"},
    {"at": 5, "type": "get", "host": 0, "uri": "ccnx:/test/video1"},
    {"at": 5, "type": "get", "host": 1, "uri": "ccnx:/test/data1"}
  ]
}
```

**`put` event optional fields:**

| Field | Type | cefputfile flag | Description |
|-------|------|----------------|-------------|
| `rate` | int/float | `-r` | Transfer rate (Mbps) |
| `block_size` | int | `-b` | Max payload length (bytes) |
| `expiry` | int/float | `-e` | Content Object lifetime (seconds) |
| `cache_time` | int/float | `-t` | Cache deletion period (seconds) |
| `valid_algo` | str | `-v` | Validation algorithm (crc32c / rsa-sha256) |
| `port_num` | int | `-p` | Port number |

**`get` event optional fields:**

| Field | Type | cefgetfile flag | Description |
|-------|------|----------------|-------------|
| `owner_only` | bool | `-o` | Owner-only mode |
| `chunk` | int | `-m` | Max chunks to retrieve |
| `pipeline` | int | `-s` | Pipeline count |
| `valid_algo` | str | `-v` | Validation algorithm (crc32c / rsa-sha256) |
| `port_num` | int | `-p` | Port number |
| `sg` | int | `-z` | Send Long Life Interest |

Note: In disaster topology, `expiry` and `cache_time` default to 3000 if not specified. In `run_cefputfile()` itself, they default to None (flag omitted).
`pubsub_pub.pub_opts` does not acquire this default; omitted values remain
omitted.

YAML example with event content operations:
```yaml
hosts: 10
switches: 15
seed: 42
events:
  - {at: 5, type: put, host: 9, uri: "ccnx:/test/content1", file: "./sample-putfile"}
  - {at: 10, type: get, host: 0, uri: "ccnx:/test/content1"}
```

Top-level `puts`, `gets`, and `auto` are ignored with a warning. Use
`events` for all content operations.

`ceforeemu-connect` supports publication events only: `put` and
`pubsub_pub` select publisher roles, program URI-specific FIB state, and are
seeded before the CLI starts. `get` and `pubsub_sub` events are warned about
but are not executed automatically.

**Topology PNG Output:**
```bash
--topo-png output.png           # Output path
--topo-layout spring            # Layout: spring, kamada_kawai, circular
```

## Log Summarization

The `ceforeemu-log` command collects cefputfile/cefgetfile/cefpubfile/cefsubfile logs from experiment directories and outputs per-command CSV files.

**Basic usage:**
```bash
ceforeemu-log logs/ex1_seed42/
```

**Multiple directories (cross-experiment comparison):**
```bash
ceforeemu-log logs/ex1_seed42/ logs/ex5_seed42/ -o results/
```

**Pipe-friendly stdout output:**
```bash
ceforeemu-log logs/ex1_seed42/ --stdout | head -20
```

If not installed, use `uv run ceforeemu-log` instead.

### Supported Log Filename Patterns

| Pattern | Example | Extracted Fields |
|---------|---------|-----------------|
| host+content | `cefputfile_h13_c10.log` | command, host_id, content_id |
| host only | `cefputfile_h9.log` | command, host_id |
| disaster | `cefgetfile_seed42_downhosts0,1_idx16_h4.log` | command, host_id, seed, down_hosts, idx |
| legacy | `cefgetfile-h0.log` | command, host_id |

### CSV Column Structure

**Common metadata columns (from meta.json + filename):**

| Column | Source |
|--------|--------|
| experiment_dir | Directory name |
| num, hosts, switches, seed, k | meta.json |
| down_interval, down_duration, down_count, down_stagger, down_exclude, cache_count | meta.json |
| filename, host_id, content_id, file_seed, down_hosts, get_idx | Filename |

**cefputfile-specific columns:**
timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, tx_frames, tx_bytes, duration_sec, throughput_bps, success

**cefgetfile-specific columns:**
timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success

**cefpubfile/cefsubfile:** Columns are extracted dynamically from `[command] Key = Value` lines in the log.

## Runtime Artifacts

After running scripts, the following files appear in the root directory:

- `hN-cefnetd-log` - Forwarding daemon logs for host N
- `hN-csmgrd-log` - Cache manager logs for router hosts
- `cefputfile-log` / `cefputfile_*.log` - Publisher operation logs
- `cefgetfile-log` / `cefgetfile_*.log` - Consumer operation logs
- `recvfile_at_h0` / `recvfile_at_hN` - Retrieved content files
- `ex-seed*.png` - Topology visualization images (when --topo-png used)

## Common Modifications

**Adding a new host role:**
Modify `select_template()` in the topology script to return appropriate template (h0, h1, or h2) based on index and host count.

**Changing content URI:**
Update the `ccnx:/test` prefix in `setFib()` or `set_fib()` and corresponding `cefputfile`/`cefgetfile` commands. For disaster topology, define content operations with `events` in a JSON/YAML config.

**Adjusting cache behavior:**
Edit `config/templates/h1/csmgrd.conf` template (applies to all router nodes).

**Testing link failures:**
- Basic: Use `link_down()` function in mesh scripts
- Advanced: Use disaster topology with `--down-*` options for automated failure simulation

## Development

**Package management:**
The project uses `pyproject.toml` with uv for dependency management.
System `python3` does not have project dependencies (yaml, networkx, etc.). Always use `.venv/bin/python3` or `uv run python3` to run scripts and one-off commands.

```bash
uv sync                    # Install dependencies
uv run python3 ...         # Run with managed environment
.venv/bin/python3 ...      # Direct venv invocation (equivalent)
```

**CLI entry points** (`pyproject.toml [project.scripts]`):
- `ceforeemu` — main CLI (`src.cli.main:main`)
- `ceforeemu-log` — log summarization (`src.log.cli:main`)
- `ceforeemu-connect` — external network (`src.runtime.external_net:main`)

After modifying `[project.scripts]`, run `uv pip install -e .` to register new entry points.

**Dependencies:**
- mininet>=2.3.0
- networkx>=3.6.1 (for topology algorithms and PNG output)
- matplotlib>=3.10.8 (for PNG output)
- pyyaml>=6.0 (for YAML configuration support)

## Security Notes

- `config/templates/h*/default-private-key` files contain sensitive cryptographic material - do not commit changes or share
- All scripts require root privileges due to Mininet's network namespace manipulation
- Only run in trusted/isolated environments (VMs recommended)

## MCP Tool Settings

When using Codex MCP, specify model `gpt-5.5` (reasoning medium, summaries auto).
