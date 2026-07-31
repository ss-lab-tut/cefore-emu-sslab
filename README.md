# CeforeEmu (by sslab)

[README.md(ja)](./README_ja.md)

## Overview

CeforeEmu is a network emulator based on Mininet for testing Cefore (Content-Centric Networking framework) deployments on Ubuntu 22.04. It creates virtual network topologies with virtual hosts running Cefore daemons (*cefnetd*) to simulate content distribution scenarios.

Three topology types are available via a unified CLI:

| Subcommand | Description |
|------------|-------------|
| `linear` | Linear topology (consumer-router-publisher chain) |
| `mesh` | Random mesh topology with multi-path FIB |
| `disaster` | Mesh with periodic host failures, bandwidth control, and external interface support |
| `connect` | External network mesh with physical Cefore device connectivity |

## Prerequisites

* Cefore installed on Ubuntu 22.04
* Mininet version 2.3.0 ([https://mininet.org/](https://mininet.org/))
* Python >= 3.12
* curl (required for `compute_call` events)
* uv (required for python package management)

```bash
uv sync   # Install dependencies
```

**Python dependencies** (managed via `pyproject.toml`):
- `mininet>=2.3.0`
- `networkx>=3.6.1` (topology algorithms and PNG output)
- `matplotlib>=3.10.8` (PNG output)
- `pyyaml>=6.0` (YAML configuration support)

After modifying `[project.scripts]` in `pyproject.toml`, run `uv pip install -e .` to register new CLI entry points.

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
| `--ext host,ifname,ip[,mtu]` | Attach external interface; ip required in CIDR form (repeatable) |
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
`pubsub_pub`, `ccninfo`.

For a disaster `put` event, omitted `expiry` and `cache_time` are both sent
as `3000` to preserve the pre-events disaster behavior. Pub/sub publication
options remain explicit: omitted `pub_opts.expiry` or `pub_opts.cache_time`
uses the Cefore command default.

`compute_call` emulates edge-compute offload: the host issues an HTTP request
(`endpoint`; `method` GET/POST, default GET; optional `payload` string,
`headers` str→str dict, `timeout` seconds — default 30, bounding curl and the
command deadline), optionally saves the response (`output_file`, under the
run dir) and republishes it into the ICN (`publish_uri` → cefputfile;
requires `output_file`). `pub_opts` takes the put-style cefputfile options —
`rate` (≥0.001 Mbps), `block_size` (int ≥60), `expiry`/`cache_time` (≥1,
default `3000`), `valid_algo` (crc32c/rsa-sha256), `port_num` (int ≥1) — and
unknown keys are rejected. The cefputfile run has its own deadline,
`publish_timeout` (positive number, default 120s; publishing speed is
governed by `rate`, not the HTTP timeout). Success is strict — curl exit 0
AND HTTP 2xx AND, when publishing, cefputfile exit 0 with neither run timed
out nor cancelled — and the results.json record carries a tri-state
`outcome`: `ok`; `not-ok` (HTTP failure, or a failed/timed-out/cancelled
publish); or `skipped-no-result` (environment: endpoint unreachable — curl
exit 5/6/7/28 — or the HTTP run timed out / was cancelled) plus a `detail`
dict (`http_status`,
`curl_exit`, `publish_ok`, `output_file`). A `publish_uri`-bearing
compute_call also joins the disaster scenario's publisher metadata so FIB
pre-programming routes consumers toward the republished content. `repeat`
supports `interval`/`count` only (restore forms and unknown keys are
rejected).

`ceforeemu-connect` uses `put` and `pubsub_pub` events only to identify
publishers, program URI-specific FIB entries, and seed publications before
opening its CLI. It warns and does not automatically execute `get`,
`pubsub_sub`, or `ccninfo` events. Legacy top-level content keys are not
restored.

**Monitoring:**
```yaml
monitoring:
  interval: 5
  output_json: "monitor.json"
  output_csv: "monitor.csv"
  targets:
    - {type: cefstatus, hosts: "all"}
    - {type: csmgrstatus, hosts: "cache"}
    - {type: ccninfo, hosts: [0], uri: "ccnx:/test/sample", cache_info: true}
```

**Cache configuration (`cache_config`):**
Supersedes legacy `cache_count`/`cache_default_rct_ms` when present.
```yaml
cache_config:
  strategy: "k_centers"    # k_centers / manual / degree_based / random
  default:
    count: 3
    capacity: 819200
    default_rct_ms: 1800000
    algorithm: "LRU"       # LRU / LFU / FIFO / None
    type: "memory"         # memory / filesystem
```

**Failure scenarios (`failure_scenarios`):**
Supersedes legacy `down_interval`/`down_duration`/etc when present.
```yaml
failure_scenarios:
  strategy: "cyclic"       # simple / cyclic / random / manual
  cycles:
    - {interval: 30, duration: 10, count: 2}
```

**Routing strategy (`routing`):**
```yaml
routing:
  strategy: "dijkstra"     # dijkstra / shortest_path / ecmp
```

**Forwarding configuration (`forwarding_config`):**
Config-only (no CLI flag); valid in `disaster` and `connect` blocks.
```yaml
forwarding_config:
  default: "flooding"       # default / flooding / shortest_path
  nodes:
    - {id: [3, 5], strategy: "shortest_path"}
```
Written into every `hN/cefnetd.conf` as `FORWARDING_STRATEGY` before `cefnetd`
starts (post-start edits do not take effect). A `nodes` entry overrides
`default` for its host IDs; an unspecified `default` resolves to `"flooding"`,
matching the template status quo.

See `config/examples/example.yaml` for the complete reference with all parameters.

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

### Log Filename Schema

All content logs use the single canonical pattern owned by `src/core/artifacts.py`
(2026-07-03 artifact-layout change — the former host+content / disaster / legacy
patterns are no longer written or parsed):

| Pattern | Example | Extracted Fields |
|---------|---------|-----------------|
| canonical | `cefgetfile_eval_h4_test_sample.log` | command, phase, host, label |

Operation context beyond the filename (URI, success, down hosts) is joined from
the same directory's `results.json` via its `log_file` key.

### CSV Column Structure

**Common metadata columns (from meta.json + filename + results.json):**

| Column | Source |
|--------|--------|
| experiment_dir | Directory name |
| num, hosts, switches, seed, k | meta.json |
| down_interval, down_duration, down_count, down_stagger, down_exclude, cache_count, forwarding_default | meta.json |
| filename, host_id, phase, label | Filename |
| down_hosts, publisher_down | results.json join |

**cefputfile-specific columns:**
timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, tx_frames, tx_bytes, duration_sec, throughput_bps, success

**cefgetfile-specific columns:**
timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success

**cefpubfile/cefsubfile-specific columns:** columns are schema-defined per
command in `src/log/schema.py` (`COMMAND_SCHEMAS`), not discovered dynamically.
`cefsubfile` carries the same metric set as `cefgetfile`:
timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success

`cefpubfile` carries the put-side config metrics plus two presence markers
(`trigger_interest_sent`/`trigger_data_received`, from the "Send Trigger
Interest." / "Receive Trigger Data, finish application." log lines):
timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, trigger_interest_sent, trigger_data_received, success

Unknown `Key = Value` lines not covered by the schema are still parsed and
appended after the schema columns, with a stderr warning.

## Runtime Artifacts

After running scripts, the following files appear in the working directory (or under `logs/ex{num}_seed{seed}/` when `num` is set). Daemon logs are collected only when a run directory is explicitly selected; current-directory runs leave the `/tmp` daemon logs uncollected.

- `cefnetd_<port>_<sockid>.log` — Forwarding daemon logs collected from `/tmp`
- `csmgrd_<port>_<sockid>.log` — Cache manager logs collected from `/tmp`
- `cefputfile-log` / `cefputfile_*.log` — Publisher operation logs
- `cefgetfile-log` / `cefgetfile_*.log` — Consumer operation logs
- `recvfile_at_h0` / `recvfile_at_hN` — Retrieved content files
- `ex-seed*.png` — Topology visualization images (when `--topo-png` used)

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
│   │   │   └── validator.py       # Config validation
│   │   ├── artifacts.py           # Artifact naming (dir / PNG / log names, build+parse)
│   │   ├── fib.py                 # FIB route computation
│   │   ├── flap_state.py          # Host flap state tracking
│   │   ├── graph.py               # Graph algorithms (Dijkstra, k-center)
│   │   ├── paths.py               # Output path resolution
│   │   ├── roles.py               # Node role assignment
│   │   └── tee.py                 # Tee stdout/stderr to file
│   ├── log/                       # Log parsing and CSV summarization
│   │   ├── parser.py              # Log text → dict parser
│   │   ├── plotter.py             # Log data plotting
│   │   ├── summarizer.py          # Directory walk + CSV output
│   │   └── cli.py                 # argparse CLI
│   ├── runtime/                   # Runtime operations
│   │   ├── bandwidth.py           # Link bandwidth control
│   │   ├── bridge_args.py         # Bridge CLI argument parsing
│   │   ├── bridge_external.py     # External NIC bridge attachment
│   │   ├── bridge_root.py         # Root namespace bridge orchestration
│   │   ├── cache_manager.py       # Cache manager operations
│   │   ├── cef_argv.py            # Cefore command argv builder
│   │   ├── cefore.py              # Cefore daemon start/stop/wait
│   │   ├── cleanup.py             # Cleanup utilities
│   │   ├── command_runner.py      # CommandRunner seam (host command execution)
│   │   ├── content_ops.py         # Content operations (put/get/pub/sub)
│   │   ├── external_net.py        # External network mesh scenario
│   │   ├── failure_manager.py     # Host failure simulation
│   │   ├── links.py               # Link state control (up/down)
│   │   ├── monitoring.py          # Periodic status collection
│   │   ├── net_config.py          # IP address & FIB application
│   │   ├── result_detect.py       # Result/success detection
│   │   ├── scheduler.py           # Timed event scheduler
│   │   ├── template.py            # Host directory template management
│   │   ├── topo.py                # Mininet Topo subclass (MeshTopo)
│   │   └── viz.py                 # Topology visualization & PNG output
│   └── scenarios/                 # Scenario implementations
│       ├── base.py                # Shared scenario utilities
│       ├── connect.py             # External network connectivity scenario
│       ├── linear.py              # Linear topology scenario
│       ├── mesh.py                # Mesh topology scenario
│       └── disaster.py            # Mesh with disaster simulation
│
├── config/                        # Configuration
│   ├── templates/                 # Host templates (h0, h1, h2)
│   └── examples/                  # Example configurations (YAML/JSON)
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

## Architecture

### Topology Scripts Structure

All topology scripts follow a common pattern:

1. **Topology Definition** — Mininet Topo subclass defines network structure
2. **IP Address Assignment** — Each link gets a /24 subnet (192.168.X.Y)
3. **Cefore Daemon Startup** — Start csmgrd (cache managers) and cefnetd (forwarding daemons)
4. **FIB Configuration** — Set forwarding rules using `cefroute add`
5. **Content Operations** — Publisher runs `cefputfile`, consumer runs `cefgetfile`
6. **Cleanup** — Stop daemons and remove temporary host directories

### Host Configuration Templates

Templates are located in `config/templates/`:

- `h0/` — Consumer template (CS_MODE=0, no caching)
- `h1/` — Router template (CS_MODE=2, external cache manager)
- `h2/` — Publisher template (CS_MODE=1, local cache mode)

For topologies with >3 hosts, additional directories (h3, h4, ...) are generated dynamically by copying templates and cleaned up after script completion via `cleanup_node_dirs()`.

**Configuration files per host:**
- `cefnetd.conf` — Forwarding daemon config (includes LOCAL_SOCK_ID)
- `cefnetd.fib` — Static forwarding table
- `csmgrd.conf` — Cache manager config
- `conpubd.conf` — Publisher daemon config
- `plugin.conf` — Plugin configuration
- `cefnetd.key` — Key configuration
- `default-private-key`, `default-public-key` — Cryptographic keys (sensitive)

### Key Functions

**IP Address Assignment:**
- Linear topologies: Sequential /24 subnets (192.168.0.x, 192.168.1.x, ...)
- Mesh topologies: One /24 per link, host ID determines last octet

**FIB Configuration (`src/core/fib.py`, `src/runtime/net_config.py`):**
- Linear: Forward all interests toward publisher (next hop in line)
- Mesh: Uses per-source Dijkstra for efficient multipath routing
  - `dijkstra_all()`: Computes shortest distances from a source to all destinations (`src/core/graph.py`)
  - `shortest_path()`: Dijkstra's algorithm with edge/node banning support (constrained pathfinding)
  - `k_shortest_paths()`: Yen's algorithm for k alternate paths
  - `compute_fib()`: Computes FIB entries for all destinations with default URI pattern `ccnx:/test/exampleN`
  - `compute_fib_for_uris()`: Computes FIB entries for specific URI-to-publisher mappings (publication events)
  - `apply_fib()`: Applies computed FIB entries to live Mininet hosts via `cefroute add` (`src/runtime/net_config.py`)

**Dynamic Configuration (`src/runtime/template.py`, `src/core/roles.py`):**
- `update_local_sock_id()`: Modifies LOCAL_SOCK_ID in config files to avoid socket conflicts
- `provision_node_dirs()`: Creates host directories from templates for a given roles mapping; raises `NodeDirError` and rolls back partial work on failure
- `assign_roles()`: Determines `NodeRole` (CONSUMER/ROUTER/PUBLISHER) for each host index; each `NodeRole` carries a `.template` attribute (`"h0"`, `"h1"`, or `"h2"`)

**Content Operations (defined in `src/runtime/cefore.py`):**
- `run_cefputfile()`: Publish content via cefputfile with configurable options
- `run_cefgetfile()`: Retrieve content via cefgetfile with configurable options
- `run_cefpubfile()`: Publish content via cefpubfile (pub/sub model, returns a CommandHandle)
- `start_cefsubfile()`: Subscribe to content via cefsubfile (pub/sub model, returns a CommandHandle)

**Status/Info Commands:**
- `run_csmgrstatus()`: Query cache manager status via csmgrstatus
- `cefroute_del()`: Delete a FIB entry via `cefroute del`
- `cefroute_enable()`: Enable a FIB entry via `cefroute enable`

## Common Modifications

**Adding a new host role:**
Modify `assign_roles()` in `src/core/roles.py` to return the appropriate `NodeRole` (CONSUMER/ROUTER/PUBLISHER) based on index and host count. Each `NodeRole` carries a `.template` attribute that maps to the `config/templates/hN` directory.

**Changing content URI:**
Update the URI prefix in `compute_fib()` / `compute_fib_for_uris()` (`src/core/fib.py`) and corresponding `cefputfile`/`cefgetfile` commands. For disaster topology, define content operations with `events` in a JSON/YAML config.

**Adjusting cache behavior:**
Edit `config/templates/h1/csmgrd.conf` (applies to all router nodes).

**Testing link failures:**
- Basic: Use `link_down()` / `link_up()` in `src/runtime/links.py`
- Advanced: Use disaster topology with `--down-*` options or `failure_scenarios` in a config file

## Documents

- [CONTEXT.md](CONTEXT.md) - Project glossary (domain language)

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
