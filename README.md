# CeforeEmu

[README.md(ja)](./README_ja.md)

## Overview

CeforeEmu is a network emulator based on Mininet for testing Cefore (Content-Centric Networking framework) deployments on Ubuntu 22.04. It creates virtual network topologies with virtual hosts running Cefore daemons (*cefnetd*) to simulate content distribution scenarios.

Three topology types are available via a unified CLI:

| Subcommand | Description |
|------------|-------------|
| `linear` | Linear topology (consumer-router-publisher chain) |
| `mesh` | Random mesh topology with multi-path FIB |
| `disaster` | Mesh with periodic host failures, bandwidth control, and external interface support |

## Prerequisites

* Cefore installed on Ubuntu 22.04
* Mininet version 2.3.0 ([https://mininet.org/](https://mininet.org/))
* Python >= 3.12
* curl (required for `compute_call` events)
* uv (required for python package management)

```bash
uv sync   # Install dependencies
```

## Quick Start

```bash
# Linear topology (3 nodes by default)
sudo .venv/bin/python3 -m src linear

# Linear topology with 7 hosts
sudo .venv/bin/python3 -m src linear --hosts 7

# Mesh topology
sudo .venv/bin/python3 -m src mesh --hosts 8 --switches 12 --seed 42 --k 3

# Disaster topology with config file
sudo .venv/bin/python3 -m src disaster --config config/examples/example.yaml

# Exit Mininet CLI
mininet> exit
```

If installed via `uv` / `pip install -e .`, the `ceforeemu` command is also available:

```bash
sudo ceforeemu linear --hosts 5
sudo ceforeemu disaster --config config/examples/example.yaml
```

### UDP Buffer Configuration

```bash
./buffer.sh   # Increases UDP buffer sizes for Cefore
```

## Topology Types

### linear

Simple linear chain: h0 (consumer) - s0 - h1 (router) - s1 - ... - hN (publisher).

```bash
sudo .venv/bin/python3 -m src linear --hosts 5
```

### mesh

Random mesh of hosts connected by switches. Each destination host hX maps to prefix `ccnx:/test/example{X+1}` and uses k-shortest paths for FIB.

```bash
sudo .venv/bin/python3 -m src mesh --hosts 8 --switches 12 --seed 42 --k 3
```

Key options:

| Option | Description |
|--------|-------------|
| `--hosts` | Number of hosts |
| `--switches` | Number of switches (>= 2) |
| `--seed` | Random seed for deterministic topology |
| `--k` | Number of shortest paths per destination (default: 2) |
| `--node-per-switch` | Max hosts per switch (0=unlimited, default: 2) |
| `--host-degree-min` | Minimum switches per host (default: 1) |
| `--host-degree-max` | Maximum switches per host (default: 2) |
| `--topo-png` | Output path for topology PNG |
| `--topo-layout` | Layout: spring, kamada_kawai, circular |

### disaster

Mesh topology with periodic host down/up cycles, bandwidth control, external interface attachment, and event-driven content operations.

```bash
sudo .venv/bin/python3 -m src disaster --hosts 10 --switches 15 --seed 42 \
  --down-interval 30 --down-duration 10 --down-count 2
```

Key options:

| Option | Description |
|--------|-------------|
| `--down-interval` | Seconds between down events (0 to disable) |
| `--down-duration` | Seconds to keep host down |
| `--down-count` | Number of hosts down per cycle |
| `--down-stagger` | Seconds to stagger down events within a cycle |
| `--down-exclude` | Comma-separated host IDs to exclude |
| `--cache-count` | Number of cache nodes (0 = down-count + 1) |
| `--bw nodeA,nodeB,mbps` | Set link bandwidth (repeatable) |
| `--ext host,ifname[,ip][,mtu]` | Attach external interface (repeatable) |
| `--bridge switch,root_ip,local_routes[,ext,gw]` | Root namespace bridge (repeatable) |
| `--config` | JSON/YAML configuration file |
| `--no-cli` | Non-interactive mode |
| `--duration` | Evaluation duration in seconds (with `--no-cli`) |
| `--results-json` | Write get results to JSON |

## Configuration Files

Use `--config` to load settings from JSON or YAML. YAML support requires `pyyaml`.

Top-level `puts`, `gets`, and `auto` are ignored with a warning. Use `events`
for all content operations.

**Content operations (JSON):**
```json
{
  "hosts": 10,
  "switches": 15,
  "seed": 42,
  "events": [
    {"at": 5, "type": "put", "host": 9, "uri": "ccnx:/test/video1", "file": "./video.bin", "rate": 10, "expiry": 5000, "cache_time": 5000},
    {"at": 10, "type": "get", "host": 0, "uri": "ccnx:/test/video1"},
    {"at": 15, "type": "pubsub_sub", "host": 1, "uri": "ccnx:/test/live", "sub_opts": {"wait": 20}},
    {"at": 15, "type": "pubsub_pub", "host": 7, "uri": "ccnx:/test/live", "file": "./data.bin", "pub_opts": {"lifetime": 8}}
  ]
}
```

**Timed events (YAML):**
```yaml
hosts: 10
switches: 15
seed: 42
events:
  - {at: 5, type: put, host: 9, uri: "ccnx:/test/sample", file: "./sample-putfile"}
  - {at: 10, type: get, host: 0, uri: "ccnx:/test/sample"}
  - {at: 15, type: link_down, nodes: [1, 2]}
  - {at: 25, type: link_up, nodes: [1, 2]}
  - {at: 30, type: fib_del, host: 3, prefix: "ccnx:/test/sample", next_hop: "192.168.1.1"}
```

Supported event types: `link_down`, `link_up`, `fib_add`, `fib_del`,
`fib_enable`, `bw_set`, `compute_call`, `put`, `get`, `pubsub_sub`,
`pubsub_pub`.

For a disaster `put` event, omitted `expiry` and `cache_time` are both sent
as `3000` to preserve the pre-events disaster behavior. Pub/sub publication
options remain explicit: omitted `pub_opts.expiry` or `pub_opts.cache_time`
uses the Cefore command default.

`ceforeemu-connect` uses `put` and `pubsub_pub` events only to identify
publishers, program URI-specific FIB entries, and seed publications before
opening its CLI. It warns and does not automatically execute `get` or
`pubsub_sub` events. Legacy top-level content keys are not restored.

**Monitoring:**
```yaml
monitoring:
  interval: 5
  output_json: "monitor.json"
  output_csv: "monitor.csv"
  targets:
    - {type: cefstatus, hosts: "all"}
    - {type: csmgrstatus, hosts: "cache"}
```

## Log Output Directory

When `num` is specified (config or `--num`), logs are organized into a dedicated directory:

```
logs/ex{num}_seed{seed}/
├── script.log              # Script execution log
├── topology.png            # Topology diagram
├── meta.json               # Configuration snapshot
├── cefputfile_*.log        # cefputfile logs
├── cefgetfile_*.log        # cefgetfile logs
├── recvfile_*              # Received files
└── results.json            # Get results (with --results-json)
```

```bash
# Enable log directory output
sudo .venv/bin/python3 -m src disaster --num 1 --hosts 10 --switches 15 --seed 42

# Custom output directory
sudo .venv/bin/python3 -m src disaster --config config.yaml --output-dir experiments

# Add timestamp to directory name
sudo .venv/bin/python3 -m src disaster --config config.yaml --timestamp
```

## Autotest (Non-Interactive)

Single run:
```bash
sudo .venv/bin/python3 -m src disaster \
  --config config/examples/example.yaml \
  --no-cli \
  --duration 120 \
  --results-json results.json \
  --num 1
```

Batch runner:
```bash
sudo .venv/bin/python3 tools/autotest/run.py \
  --base-config config/examples/example.yaml \
  --runs 5 \
  --duration 120 \
  --out out
```

Outputs:
- `out/run_XXXX/logs/ex{num}_seed{seed}/`: per-run logs, `meta.json`, `results.json`
- `out/summary.csv`: URI-level aggregate metrics
- `out/summary.md`: human-readable summary

In autotest mode, event `at` values use one absolute clock starting when the
experiment begins. Seed puts complete before warmup, and warmup completes
before failure/evaluation; an evaluation event whose time passed during
warmup executes immediately with a late-event warning. Repeating `put` events
are rejected in autotest mode. `duration` remains the failure/evaluation
observation period after that phase starts; with no evaluation events and
`duration: 0`, no failure phase is started.

## Log Summarization

Collect cefputfile/cefgetfile/cefpubfile/cefsubfile logs and output per-command CSV files:

```bash
# Single directory
ceforeemu-log logs/ex1_seed42/

# Multiple directories (cross-experiment comparison)
ceforeemu-log logs/ex1_seed42/ logs/ex5_seed42/ -o results/

# Pipe-friendly stdout output
ceforeemu-log logs/ex1_seed42/ --stdout | head -20
```

If not installed, use `uv run ceforeemu-log` instead.

## Project Structure

```
cefore-emu/
├── src/                           # Main source code
│   ├── __init__.py
│   ├── __main__.py                # python -m src entry point
│   ├── cli/                       # CLI interface
│   │   ├── main.py                # Subcommand dispatcher
│   │   └── args.py                # Argument parser definitions
│   ├── core/                      # Core logic and algorithms
│   │   ├── config/                # Configuration utilities
│   │   │   ├── loader.py          # JSON/YAML config loader
│   │   │   └── priority_resolver.py  # Config priority resolution
│   │   ├── fib.py                 # FIB route computation
│   │   ├── flap_state.py          # Host flap state tracking
│   │   ├── graph.py               # Graph algorithms (Dijkstra, k-center)
│   │   ├── paths.py               # Output path resolution
│   │   ├── roles.py               # Node role assignment
│   │   └── tee.py                 # Tee stdout/stderr to file
│   ├── log/                       # Log parsing and CSV summarization
│   │   ├── filename.py            # Filename pattern → metadata extraction
│   │   ├── parser.py              # Log text → dict parser
│   │   ├── plotter.py             # Log data plotting
│   │   ├── summarizer.py          # Directory walk + CSV output
│   │   └── cli.py                 # argparse CLI
│   ├── runtime/                   # Runtime operations
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
│       ├── base.py                # Shared scenario utilities
│       ├── linear.py              # Linear topology scenario
│       ├── mesh.py                # Mesh topology scenario
│       └── disaster.py            # Mesh with disaster simulation
│
├── config/                        # Configuration
│   ├── templates/                 # Host templates (h0, h1, h2)
│   └── examples/                  # Example configurations (YAML/JSON)
├── doc/                           # Design documents
├── tools/
│   └── autotest/                  # Batch experiment runner
│       ├── run.py                 # Batch runner script
│       └── analyze.py             # Result analysis
│
├── sample-putfile                 # Test data (root exception)
├── buffer.sh                      # UDP buffer configuration (root exception)
├── pyproject.toml                 # Package configuration
└── CLAUDE.md                      # Development guidance
```

## Documents

- [doc/autotest_plan_reviewed.md](doc/autotest_plan_reviewed.md) - Autotest implementation plan
- [doc/cefore_emu_autotest_spec.md](doc/cefore_emu_autotest_spec.md) - Autotest specification
- [doc/branch-retirement-feature-test.md](doc/branch-retirement-feature-test.md) - Branch retirement notes

## Node Roles

| Role | Hosts | CS_MODE | Description |
|------|-------|---------|-------------|
| Consumer | h0 (first) | 0 | Requests content via `cefgetfile` |
| Router | odd-numbered | 2 | Forwards interests/content, runs `csmgrd` |
| Publisher | last host | 0 | Stores and serves content via `cefputfile` |

For topologies with >3 hosts, additional host directories are generated dynamically from templates and cleaned up after script completion.

## Addressing for External Connectivity

When connecting Mininet hosts to external physical Cefore devices via `--ext` or `bridges`, the default internal address space `192.168.0.0/16` is likely to conflict with the physical LAN. If the external device has no explicit route to the Mininet range, packets are silently dropped. In Class C Ethernet environments where other devices also use `192.168.x.x`, responses may be misrouted to the wrong host.

Change the internal address range via `addressing.network_cidr` in your config file:

| Address Range | Recommendation | Rationale |
|---------------|----------------|-----------|
| `100.64.0.0/16` | Primary | RFC 6598 Shared Address Space (CGNAT) — virtually never used on LANs, lowest collision risk |
| `172.20.0.0/16` | Fallback | RFC 1918 Class B private — less common than 192.168.x.x, but used in some enterprise LANs |

> **Note:** `network_cidr` accepts only `/16`. Specify `100.64.0.0/16`, not the full CGNAT block `100.64.0.0/10`.

```yaml
addressing:
  network_cidr: "100.64.0.0/16"
```

The external device must also have a static route pointing the Mininet range at the bridge gateway:

```bash
ip route add 100.64.0.0/16 via <bridge_root_ns_ip>
```

See `config/examples/example.yaml` for full details.

## Security Notes

- `config/templates/h*/default-private-key` files contain sensitive cryptographic material
- All scripts require root privileges due to Mininet's network namespace manipulation
- Only run in trusted/isolated environments (VMs recommended)
