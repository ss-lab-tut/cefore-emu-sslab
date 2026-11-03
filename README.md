# ReCefore (by sslab)

[![CI](https://github.com/ss-lab-tut/cefore-emu-sslab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ss-lab-tut/cefore-emu-sslab/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/ss-lab-tut/cefore-emu-sslab)](LICENSE)
[![Release](https://img.shields.io/github/v/release/ss-lab-tut/cefore-emu-sslab)](https://github.com/ss-lab-tut/cefore-emu-sslab/releases/latest)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/ss-lab-tut/cefore-emu-sslab/main/pyproject.toml)](pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/types-mypy-blue)](https://mypy-lang.org/)

[README.md(ja)](./README_ja.md)

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
  - [UDP Buffer Configuration](#udp-buffer-configuration)
- [Topology Types](#topology-types)
  - [linear](#linear)
  - [mesh](#mesh)
  - [disaster](#disaster)
- [Configuration Files](#configuration-files)
  - [Content Operations (JSON)](#content-operations-json)
  - [Timed Events (YAML)](#timed-events-yaml)
  - [compute_call Events](#compute_call-events)
  - [Events under ceforeemu-connect](#events-under-ceforeemu-connect)
  - [Monitoring](#monitoring)
  - [Cache Configuration (cache_config)](#cache-configuration-cache_config)
  - [Failure Scenarios (failure_scenarios)](#failure-scenarios-failure_scenarios)
  - [Routing Strategy (routing)](#routing-strategy-routing)
  - [Explicit Topology (links)](#explicit-topology-links)
  - [Static Prefix Routes (prefix_routes)](#static-prefix-routes-prefix_routes)
  - [Forwarding Configuration (forwarding_config)](#forwarding-configuration-forwarding_config)
  - [Host Apps (host_apps)](#host-apps-host_apps)
  - [Restarting a Host App (host_app_restart)](#restarting-a-host-app-host_app_restart)
- [Addressing for External Connectivity](#addressing-for-external-connectivity)
- [Log Output Directory](#log-output-directory)
- [Runtime Artifacts](#runtime-artifacts)
- [Autotest (Non-Interactive)](#autotest-non-interactive)
- [Log Summarization](#log-summarization)
  - [Log Filename Schema](#log-filename-schema)
  - [CSV Column Structure](#csv-column-structure)
- [Architecture](#architecture)
  - [Topology Scripts Structure](#topology-scripts-structure)
  - [Node Roles](#node-roles)
  - [Host Configuration Templates](#host-configuration-templates)
  - [Key Functions](#key-functions)
- [Project Structure](#project-structure)
- [Common Modifications](#common-modifications)
- [Continuous Integration](#continuous-integration)
- [Security Notes](#security-notes)
- [Documents](#documents)

## Overview

ReCefore is a network emulator based on Mininet for testing Cefore (Content-Centric Networking framework) deployments on Ubuntu 22.04. It creates virtual network topologies with virtual hosts running Cefore daemons (*cefnetd*) to simulate content distribution scenarios.

> **Naming:** ReCefore is the tool's name, but the code has not been renamed yet. The repository (`cefore-emu-sslab`), the package (`cefore-emu`), and the commands (`ceforeemu`, `ceforeemu-log`, `ceforeemu-connect`) keep their current names, so use them exactly as written below.

Three topology types are available via a unified CLI:

| Subcommand | Description |
|------------|-------------|
| `linear` | Linear topology (consumer-router-publisher chain) |
| `mesh` | Random mesh topology with multi-path FIB |
| `disaster` | Mesh with periodic host failures, bandwidth control, and external interface support |

A fourth topology, an external network mesh with physical Cefore device connectivity, is not a subcommand: it has its own `ceforeemu-connect` entry point.

## Prerequisites

- Cefore installed on Ubuntu 22.04
- Mininet version 2.3.0 ([https://mininet.org/](https://mininet.org/))
- Python >= 3.12
- curl (required for `compute_call` events)
- uv (required for Python package management)

```bash
uv sync   # Install dependencies
```

**Python dependencies** (managed via `pyproject.toml`):

- `flask>=3.1.3` (WebUI live dashboard)
- `mininet>=2.3.0.dev6`
- `networkx>=3.6.1` (topology algorithms and PNG output)
- `matplotlib>=3.10.8` (PNG output)
- `pyyaml>=6.0` (YAML configuration support)
- `scipy>=1.17.1`

After modifying `[project.scripts]` in `pyproject.toml`, run `uv pip install -e .` to register new CLI entry points.

## Quick Start

```bash
# Linear topology (5 hosts by default)
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
| `--ext host,ifname,ip[,mtu]` | Attach external interface; ip required in CIDR form (DHCP unsupported, repeatable) |
| `--bridge switch,root_ip,local_routes[,ext_routes,gateway]` | Root namespace bridge (repeatable) |
| `--config` | JSON/YAML configuration file |
| `--no-cli` | Non-interactive mode |
| `--duration` | Evaluation duration in seconds (with `--no-cli`) |
| `--results-json` | Write get results to JSON |

## Configuration Files

Use `--config` to load settings from JSON or YAML. YAML support requires `pyyaml`.

Top-level `puts`, `gets`, and `auto` are ignored with a warning. Use `events` for all content operations.

See `config/examples/example.yaml` for the complete reference with all parameters.

### Content Operations (JSON)

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

> **Known limitation:** the pubsub pair above is illustrative. On a 15-host / 48-switch mesh, `cefpubfile`/`cefsubfile` fail deterministically (the publisher never receives the Trigger Interest and is terminated at the deadline), even though put/get succeed on the same topology; success drops with hop distance (hop 1 succeeds, hop 3 never did). Only 3 to 5 host meshes are verified for pubsub. Keep pubsub experiments there unless you are deliberately reproducing that failure. See [docs/known-cefore-behaviors.md](docs/known-cefore-behaviors.md), "pubsub が 15-host mesh で系統的に失敗".

### Timed Events (YAML)

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

Supported event types: `link_down`, `link_up`, `fib_add`, `fib_del`, `fib_enable`, `bw_set`, `compute_call`, `put`, `get`, `pubsub_sub`, `pubsub_pub`, `ccninfo`, `host_app_restart`.

For a disaster `put` event, omitted `expiry` and `cache_time` are both sent as `3000` to preserve the pre-events disaster behavior. Pub/sub publication options remain explicit: omitted `pub_opts.expiry` or `pub_opts.cache_time` uses the Cefore command default.

### compute_call Events

`compute_call` emulates edge-compute offload: the host issues an HTTP request, optionally saves the response and republishes it into the ICN.

| Option | Details |
|---|---|
| `host` | Index of the host issuing the request; required |
| `endpoint` | HTTP request URL; required |
| `method` | GET/POST, default GET |
| `payload` | optional string |
| `headers` | optional str→str dict |
| `timeout` | seconds — default 30, bounding curl and the command deadline |
| `output_file` | Where to save the response, under the run dir |
| `publish_uri` | Republishes the saved response into the ICN via cefputfile; requires `output_file` |
| `pub_opts` | takes the put-style cefputfile options, and unknown keys are rejected |
| `publish_timeout` | The cefputfile run has its own deadline: positive number, default 120s; publishing speed is governed by `rate`, not the HTTP timeout |

`pub_opts` keys:

- `rate` (≥0.001 Mbps)
- `block_size` (int ≥60)
- `expiry`/`cache_time` (≥1, default `3000`)
- `valid_algo` (crc32c/rsa-sha256)
- `port_num` (int ≥1)

Success is strict — curl exit 0 AND HTTP 2xx AND, when publishing, cefputfile exit 0 with neither run timed out nor cancelled.

The results.json record carries a tri-state `outcome` plus a `detail` dict (`http_status`, `curl_exit`, `publish_ok`, `output_file`):

- `ok`
- `not-ok` (HTTP failure, or a failed/timed-out/cancelled publish)
- `skipped-no-result` (environment: endpoint unreachable — curl exit 5/6/7/28 — or the HTTP run timed out / was cancelled)

Related behavior:

- A `publish_uri`-bearing compute_call also joins the disaster scenario's publisher metadata so FIB pre-programming routes consumers toward the republished content.
- `repeat` supports `interval`/`count` only (restore forms and unknown keys are rejected).
- The ok path is covered by root-gated product tests under `tests/synthetic/` (hermetic, plus an HPC-backed variant); see `docs/runbooks/compute-ok-path.md`.

### Events under ceforeemu-connect

`ceforeemu-connect` uses `put` and `pubsub_pub` events only to identify publishers, program URI-specific FIB entries, and seed publications before opening its CLI. It warns and does not automatically execute `get`, `pubsub_sub`, or `ccninfo` events. Legacy top-level content keys are not restored.

### Monitoring

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

### Cache Configuration (cache_config)

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

### Failure Scenarios (failure_scenarios)

Supersedes legacy `down_interval`/`down_duration`/etc. when present.

```yaml
failure_scenarios:
  strategy: "cyclic"       # simple / cyclic / random / manual
  cycles:
    - {interval: 30, duration: 10, count: 2}
```

### Routing Strategy (routing)

```yaml
routing:
  strategy: "dijkstra"     # dijkstra / shortest_path / ecmp
```

### Explicit Topology (links)

Config-only (no CLI flag); `disaster` only. `connect` shares the same topology-build code mechanically, but its config rejects a `links` key outright — connect's bridge/k-centers cache-placement path has no test coverage for an explicit-link topology. Fixes the exact mesh instead of the seeded random MeshTopo build; omitting it keeps the random-mesh behavior byte-identical to before this option existed.

```yaml
links:
  - [0, 1]
  - [1, 2]
```

- Each pair is a 0-based host index.
- One switch is created per pair, so a `link_down`/`link_up` event (`nodes: [a, b]`) always addresses exactly that pair.
- `links` must describe a connected graph spanning every host `0..hosts-1`, or config validation rejects it with the specific problem:
  - indices in range
  - no self-links
  - no duplicate pairs
  - no disconnected host
  - at most 255 links
  - no host index above 253 — the addressing scheme's one-`/24`-per-link, `host_idx + 1`-as-4th-octet layout has no more room than that
- `switches`, `node_per_switch`, `host_degree_min`, `host_degree_max`, and `switch_use_all` only control the random mesh build; a non-default value for any of them alongside `links` is rejected as a config error rather than silently ignored (leave them unset/default).
- A `bridges[i].switch` index is checked against `len(links)` instead of `switches` once `links` is set, since `links` is what actually determines the switch count.
- See `config/examples/min_explicit_line.yaml` for a 3-host line with a `link_down`/`link_up` cycle.

### Static Prefix Routes (prefix_routes)

Config-only (no CLI flag); `disaster` only — `connect` rejects it the same way it rejects `links`, since only `DisasterScenario.configure` reads it.

```yaml
prefix_routes:
  "ccnx:/test/to-h2": 2
  "ccnx:/test/to-h0": 0
```

- Each entry announces that every host other than the named one gets a FIB route toward it, computed with the same shortest-path/next-hop logic as every other route (`core.fib.compute_fib_for_uris`).
- Unlike a put/pubsub_pub publisher, a `prefix_routes` entry is one-directional only (nothing ever originates a Reflexive-Forwarding route back).
- It is independent of whether any publisher exists in the same config: its routes are always computed, with or without `put`/`pubsub_pub` events (routes from an actual publisher are unaffected and still get both directions).
- Keys must be non-empty `ccnx:/` URI strings; values must be an integer host index in range.
- See `config/examples/min_prefix_routes.yaml` for a 3-host line with `debug.artifacts: [fib_dump]` capturing the installed FIB.

### Forwarding Configuration (forwarding_config)

Config-only (no CLI flag); valid in `disaster` and `connect` blocks.

```yaml
forwarding_config:
  default: "flooding"       # default / flooding / shortest_path
  nodes:
    - {id: [3, 5], strategy: "shortest_path"}
```

Written into every `hN/cefnetd.conf` as `FORWARDING_STRATEGY` before `cefnetd` starts (post-start edits do not take effect). A `nodes` entry overrides `default` for its host IDs; an unspecified `default` resolves to `"flooding"`, matching the template status quo.

### Host Apps (host_apps)

Config-only (no CLI flag). Starts one or more arbitrary, long-running processes per host, after cefnetd/csmgrd come up, and stops them before teardown stops cefnetd/csmgrd (mirrors `DaemonFleet`'s start/stop shape: each host's stop is independent, and failures are aggregated instead of aborting the rest). ReCefore has no knowledge of what the app does or why — it only expands four placeholders and launches/stops the argv through `CommandRunner.start`.

```yaml
host_apps:
  - hosts: [0, 1, 2]        # or "all"
    argv: ["sh", "-c", "echo {node} {t0_ms} > {node_dir}/marker"]
    cwd: "{node_dir}"                       # optional
    env: {CEFORE_DIR: "{cefore_conf_dir}"}   # optional
    log: "{node_dir}/{node}.log"             # optional
```

- `env`: `CommandRunner.start` has no env kwarg, so this becomes an `env K=V ...` argv prefix.
- `log`: must contain one of `{node}`, `{node_dir}`, or `{cefore_conf_dir}` when `hosts` is `"all"` or more than one host, or every host truncates the same file.

Placeholders, expanded in `argv`/`env`/`cwd`/`log`:

| Placeholder | Value |
|---|---|
| `{node}` | Node name (`h3`) |
| `{node_dir}` | Absolute path of that host's directory |
| `{cefore_conf_dir}` | Absolute path of the directory holding that host's `cefnetd.conf` — the value cefpyco's `create_handle(ceforedir=...)` wants. Identical to `{node_dir}` today; named separately on purpose |
| `{t0_ms}` | Epoch ms taken at the same instant the scheduler treats as `at: 0`, so a host app's own relative-time math lines up with scheduled events |

See `config/examples/min_host_apps.yaml` for a runnable example.

### Restarting a Host App (host_app_restart)

```yaml
events:
  - {at: 30, type: host_app_restart, host: 2, downtime_s: 5}
```

- A scheduled event (next to `link_down`/`link_up`, not a `host_apps:` field) that stops and then restarts every `host_apps:` process configured for one host — the generic primitive for scripting "an application on host N crashes/restarts at time t" from YAML.
- `host` is required; `downtime_s` (the gap between stop and restart) is optional, finite, and defaults to 0.
- Config validation rejects a `host` with no `host_apps:` entry covering it.
- This is unrelated to the periodic host-down/host-up flap under `failure_scenarios` (or legacy `down_interval`/`down_duration`): that mechanism only toggles link state and never touches `host_apps:` processes, which is exactly the gap `host_app_restart` fills.
- The restarted process gets the exact `argv`/`cwd`/`env` and `{t0_ms}` its first life was launched with (never re-expanded, never re-captured); only its log path differs, with a `.lifeN` suffix (`N` >= 2) so a restarted life's log cannot truncate the previous life's output.
- The scheduler thread blocks for the full `downtime_s`, so any other event scheduled to fire during that window runs late by that amount — the same cost any slow handler imposes on ReCefore's single-threaded `EventScheduler`.
- The `results.json` record is a plain success/failure event row, the same shape as `link_down`/`link_up` (no tri-state `outcome`).
- See `config/examples/min_host_app_restart.yaml` for a runnable example.

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

## Log Output Directory

Logs are organized into a dedicated directory under `--output-dir` (default: `logs`), named `ex{num}_seed{seed}` when `num` is specified (config or `--num`) and `seed{seed}` otherwise:

```text
logs/ex{num}_seed{seed}/
├── script.log              # Script execution log
├── ex{num}_seed{seed}_h{hosts}.png  # Topology diagram (see Runtime Artifacts)
├── meta.json               # Configuration snapshot
├── cefnetd_<port>_<sockid>.log  # cefnetd logs collected from /tmp
├── csmgrd_<port>_<sockid>.log   # csmgrd logs collected from /tmp
├── cefputfile_*.log        # cefputfile logs
├── cefgetfile_*.log        # cefgetfile logs
├── *recvfile_*             # Received files
└── results.json            # Get results (with --results-json)
```

```bash
# Name the log directory after the experiment number
sudo .venv/bin/python3 -m src disaster --num 1 --hosts 10 --switches 15 --seed 42

# Custom output directory
sudo .venv/bin/python3 -m src disaster --config config.yaml --output-dir experiments

# Add timestamp to directory name
sudo .venv/bin/python3 -m src disaster --config config.yaml --timestamp
```

## Runtime Artifacts

After running scripts, the following files appear in the run directory. Passing `--output-dir ""` without `num` runs in the current directory instead, which leaves the `/tmp` daemon logs uncollected.

- `cefnetd_<port>_<sockid>.log` — Forwarding daemon logs collected from `/tmp`
- `csmgrd_<port>_<sockid>.log` — Cache manager logs collected from `/tmp`
- `cefputfile_*.log` — Publisher operation logs
- `cefgetfile_*.log` — Consumer operation logs
- `recvfile_at_h0` / `recvfile_at_hN` — Retrieved content files (linear, mesh)
- `{phase}_recvfile_h{host}_{label}` — Retrieved content files (event-driven runs)
- `ex{num}_seed{seed}_h{hosts}.png` — Topology visualization image. `disaster` and `connect` write it by default (`seed{seed}_h{hosts}.png` without `num`), `mesh` writes one only with `--topo-png`, and `linear` writes none. `--topo-png` sets the name, always under the run directory.

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

In autotest mode, event `at` values use one absolute clock starting when the experiment begins. Seed puts complete before warmup, and warmup completes before failure/evaluation; an evaluation event whose time passed during warmup executes immediately with a late-event warning. Repeating `put` events are rejected in autotest mode. `duration` remains the failure/evaluation observation period after that phase starts; with no evaluation events and `duration: 0`, no failure phase is started.

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

All content logs use the single canonical pattern owned by `src/core/artifacts.py` (2026-07-03 artifact-layout change — the former host+content / disaster / legacy patterns are no longer written or parsed):

| Pattern | Example | Extracted Fields |
|---------|---------|-----------------|
| canonical | `cefgetfile_eval_h4_test_sample.log` | command, phase, host, label |

Operation context beyond the filename (URI, success, down hosts) is joined from the same directory's `results.json` via its `log_file` key.

### CSV Column Structure

**Common metadata columns (from meta.json + filename + results.json):**

| Column | Source |
|--------|--------|
| experiment_dir | Directory name |
| num, hosts, switches, seed, k | meta.json |
| down_interval, down_duration, down_count, down_stagger, down_exclude, cache_count, forwarding_default | meta.json |
| filename, host_id, phase, label | Filename |
| down_hosts, publisher_down | results.json join |

**Command-specific columns:**

| Command | Columns |
|---------|---------|
| `cefputfile` | timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, tx_frames, tx_bytes, duration_sec, throughput_bps, success |
| `cefgetfile` | timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success |
| `cefsubfile` | timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success |
| `cefpubfile` | timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, trigger_interest_sent, trigger_data_received, success |

Columns are schema-defined per command in `src/log/schema.py` (`COMMAND_SCHEMAS`), not discovered dynamically.

- `cefsubfile` carries the same metric set as `cefgetfile`.
- `cefpubfile` carries the put-side config metrics plus two presence markers (`trigger_interest_sent`/`trigger_data_received`, from the "Send Trigger Interest." / "Receive Trigger Data, finish application." log lines).

For `cefpubfile` and `cefsubfile`, unknown `Key = Value` lines not covered by the schema are still parsed and appended after the schema columns, with a stderr warning.

## Architecture

### Topology Scripts Structure

All topology scripts follow a common pattern:

1. **Topology Definition** — Mininet Topo subclass defines network structure
2. **IP Address Assignment** — Each link gets a /24 subnet (192.168.X.Y)
3. **Cefore Daemon Startup** — Start csmgrd (cache managers) and cefnetd (forwarding daemons)
4. **FIB Configuration** — Set forwarding rules using `cefroute add`
5. **Content Operations** — Publisher runs `cefputfile`, consumer runs `cefgetfile`
6. **Cleanup** — Stop daemons and remove temporary host directories

### Node Roles

| Role | Hosts | Template CS_MODE | Description |
|------|-------|------------------|-------------|
| Consumer | h0 (first) | 0 | Requests content via `cefgetfile` |
| Router | odd-numbered | 2 | Forwards interests/content, runs `csmgrd` |
| Publisher | last host | 1 | Stores and serves content via `cefputfile` |

The table shows the common case; `assign_roles()` (`src/core/roles.py`) has the exact rules. What happens to the template value depends on the scenario and cache strategy:

- `linear` and `mesh` keep the template value.
- `disaster` (with `cache_config.strategy` other than `random`) and `connect` use `apply_cache_node_settings()` (`src/runtime/template.py`): cache nodes are forced to `CS_MODE=2`, non-cache publishers to `CS_MODE=1`, and any other non-cache node whose template says 2 drops to `CS_MODE=0`.
- `disaster` with `cache_config.strategy: random` uses `assign_random_cs_modes()` (`src/core/roles.py`) instead: publishers get `CS_MODE` 1 or 2, and other hosts get 0, 1, or 2.

### Host Configuration Templates

Templates are located in `config/templates/`:

- `h0/` — Consumer template (CS_MODE=0, no caching)
- `h1/` — Router template (CS_MODE=2, external cache manager)
- `h2/` — Publisher template (CS_MODE=1, local cache mode)

Host directories (h0, h1, ...) are generated dynamically by copying templates and cleaned up after script completion via `cleanup_node_dirs()`.

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
  - `shortest_path()` (`src/core/graph.py`): Dijkstra's algorithm with edge/node banning support (constrained pathfinding)
  - `k_shortest_paths()` (`src/core/graph.py`): Yen's algorithm for k alternate paths
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
- `cefroute_del()` (`src/runtime/net_config.py`): Delete a FIB entry via `cefroute del`
- `cefroute_enable()` (`src/runtime/net_config.py`): Enable a FIB entry via `cefroute enable`

## Project Structure

```text
cefore-emu-sslab/
├── src/                 # Main source code (python -m src entry point)
│   ├── cli/             # CLI interface and argument parsing
│   ├── core/            # Core logic and algorithms
│   │   └── config/      # JSON/YAML config loading and validation
│   ├── log/             # Log parsing and CSV summarization
│   ├── runtime/         # Runtime operations on live hosts and daemons
│   ├── scenarios/       # Scenario implementations (linear, mesh, disaster, connect)
│   └── webui/           # WebUI live dashboard
├── config/
│   ├── templates/       # Host templates (h0, h1, h2)
│   └── examples/        # Example configurations (YAML/JSON)
├── tools/
│   ├── autotest/        # Batch experiment runner and result analysis
│   └── workshop/        # Workshop campaign runner, plots, report
├── tests/               # Test suite
├── docs/                # ADRs, runbooks, known Cefore behaviors
├── sample-putfile       # Test data
├── buffer.sh            # UDP buffer configuration
└── pyproject.toml       # Package configuration
```

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

## Continuous Integration

Every PR to `main` and every push on `main` runs the unit-surface gates on GitHub Actions (`.github/workflows/ci.yml`): pytest with a coverage floor (`fail_under=85`), ruff, mypy (zero errors on the default config), `uv lock --check`, and an entry-points install check. Mininet-live end-to-end evidence is deliberately *not* part of CI — it stays with the local root smoke battery (cefore-run-tests). See [docs/adr/0004](docs/adr/0004-ci-guards-unit-surface-only.md) for the decision record.

## Security Notes

- `config/templates/h*/default-private-key` files contain sensitive cryptographic material
- All scripts require root privileges due to Mininet's network namespace manipulation
- Only run in trusted/isolated environments (VMs recommended)

## Documents

- [CONTEXT.md](CONTEXT.md) - Project glossary (domain language)
