# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CeforeEmu is a network emulator based on Mininet for testing Cefore (Content-Centric Networking framework) deployments. It creates virtual network topologies with virtual hosts running Cefore daemons (cefnetd) to simulate content distribution scenarios.

**External Dependencies:**
- Cefore must be installed on Ubuntu 22.04
- Mininet version 2.3.0 must be installed
- All scripts require root privileges (sudo)

## Project Structure

The project follows a **Ports and Adapters** architecture with four layers:

```
src/
├── core/                          # Pure Python (no Mininet dependency, testable)
│   ├── graph.py                   # Graph algorithms: dijkstra, k_shortest_paths, UnionFind
│   ├── fib.py                     # Pure FIB computation (LinkSubnet, Route dataclasses)
│   ├── roles.py                   # NodeRole dataclass and assign_roles()
│   ├── flap_state.py              # Thread-safe FlapState for host failure tracking
│   ├── paths.py                   # ROOT_DIR, TEMPLATE_ROOT, resolve_run_dir()
│   └── config/                    # Configuration utilities
│       ├── loader.py              # JSON/YAML config loader
│       └── auto_gen.py            # Auto put/get operation generation
│
├── runtime/                       # Mininet/Cefore integration (concrete implementations)
│   ├── base.py                    # Runtime ABC, MininetRuntime, FakeRuntime
│   ├── cefore.py                  # Daemon control: start/stop cefnetd, csmgrd
│   ├── template.py                # Template copy, ensure_node_dirs(), cleanup_node_dirs()
│   ├── net_config.py              # apply_ip_addr(), apply_fib(), apply_fib_for_uris()
│   ├── topo.py                    # Topo subclasses: LineTopo, MeshTopo, SimpleLinkTopo
│   ├── links.py                   # Link state operations: set_node_links_state()
│   ├── bridge.py                  # External interface bridging (extracted from disaster)
│   ├── bandwidth.py               # Link bandwidth control (extracted from disaster)
│   └── viz.py                     # Topology visualization: render_topology_png()
│
├── scenarios/                     # Experiment orchestration
│   ├── base.py                    # BaseScenario ABC (SIGINT/exception teardown guarantee)
│   ├── linear.py                  # LinearScenario (h0-s0-h1-s1-...-sN-hN)
│   ├── mesh.py                    # MeshScenario (random mesh topology)
│   └── disaster.py                # DisasterScenario (mesh + periodic host failures)
│
├── cli/                           # CLI entry point
│   ├── main.py                    # Unified CLI with subcommands
│   └── args.py                    # Common argparse definitions
│
└── __main__.py                    # Package entry point

configs/
├── templates/                     # Host templates
│   ├── h0/                        # Consumer template (CS_MODE=0)
│   ├── h1/                        # Router template (CS_MODE=2)
│   └── h2/                        # Publisher template (CS_MODE=0)
└── examples/                      # Example configurations
    ├── multi_publisher.json       # Multiple publisher example
    └── auto_experiment.yaml       # Auto-generation example
```

### Layer Dependency Rules

```
cli/ → scenarios/ → runtime/ → core/
```

- **core/**: Pure Python only. No Mininet imports. Fully testable.
- **runtime/**: Depends on core/ and Mininet. Contains all Mininet/Cefore operations.
- **scenarios/**: Depends on runtime/ and core/. Orchestrates experiment lifecycle.
- **cli/**: Depends on scenarios/ and core/. Parses arguments and dispatches.

## Running Topology Scenarios

All scenarios use a unified CLI:

**Linear topology:**
```bash
sudo python3 -m src linear --hosts 5
```

**Mesh topology:**
```bash
sudo python3 -m src mesh --hosts 8 --switches 12 --k 3 --seed 42
```
- `--hosts`: Number of hosts (min 3)
- `--switches`: Number of switches/links (min 2, max n*(n-1)/2)
- `--k`: Number of shortest paths per destination for multipath routing (default 2)
- `--seed`: Random seed for deterministic topology generation

**Disaster topology (mesh with host failures):**
```bash
sudo python3 -m src disaster --hosts 10 --switches 15 --seed 42 \
    --down-interval 30 --down-duration 10 --down-count 2
```

**Using JSON/YAML configuration:**
```bash
sudo python3 -m src disaster --config configs/examples/multi_publisher.json
sudo python3 -m src disaster --config configs/examples/auto_experiment.yaml
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

### BaseScenario Pattern

All scenarios extend `BaseScenario` (src/scenarios/base.py) which guarantees teardown on SIGINT/exceptions:

```python
class BaseScenario(ABC):
    def execute(self):
        net = None
        try:
            topo = self.build_topology()
            net = self.create_mininet(topo)
            net.start()
            self.configure(net)
            self.run_experiment(net)
            CLI(net)
        except KeyboardInterrupt:
            pass
        finally:
            if net is not None:
                self.teardown(net)
                net.stop()
```

Subclasses implement: `build_topology()`, `configure(net)`, `run_experiment(net)`, `teardown(net)`.

### Runtime Abstraction

`runtime/base.py` defines a `Runtime` ABC with `MininetRuntime` (real) and `FakeRuntime` (for testing):
- `link_down(node_a, node_b)` / `link_up(node_a, node_b)`
- `run_cmd(node, cmd)` / `get_host(name)` / `get_links()`

### Node Role Assignment

Roles are defined in `core/roles.py` via `NodeRole` dataclass:
- **Consumer** (CS_MODE=0): Requests content via `cefgetfile`
- **Router** (CS_MODE=2, odd-numbered hosts): Forwards interests/content, runs csmgrd
- **Publisher** (CS_MODE=0): Stores and serves content via `cefputfile`

`assign_roles(host_num, rng, publishers=None)` dynamically assigns roles based on experiment definition.

### FIB Computation (Two-Phase)

1. **Pure computation** in `core/fib.py`: `compute_fib()` / `compute_fib_for_uris()` return `Route` dataclass objects
2. **Mininet application** in `runtime/net_config.py`: `apply_fib()` / `apply_fib_for_uris()` execute `cefroute add` commands

### Host Configuration Templates

Templates are located in `configs/templates/`:

- `h0/` - Consumer template (CS_MODE=0, no caching)
- `h1/` - Router template (CS_MODE=2, external cache manager)
- `h2/` - Publisher template (CS_MODE=1, local cache mode)

For topologies with >3 hosts, additional directories (h3, h4, ...) are generated dynamically via `runtime/template.py:ensure_node_dirs()`. Cleaned up after script completion via `cleanup_node_dirs()`.

**Configuration files per host:**
- `cefnetd.conf` - Forwarding daemon config (includes LOCAL_SOCK_ID)
- `cefnetd.fib` - Static forwarding table
- `csmgrd.conf` - Cache manager config
- `conpubd.conf` - Publisher daemon config
- `plugin.conf` - Plugin configuration
- `cefnetd.key` - Key configuration
- `default-private-key`, `default-public-key` - Cryptographic keys (sensitive)

### Key Functions

**Graph Algorithms (core/graph.py):**
- `dijkstra_all()`: Computes shortest distances from a source to all destinations
- `shortest_path()`: Dijkstra's with edge/node banning support
- `k_shortest_paths()`: Yen's algorithm for k alternate paths
- `select_k_centers()`: Greedy k-center selection for cache placement

**FIB Computation (core/fib.py):**
- `compute_fib()`: Pure FIB computation for all destinations with default URI pattern
- `compute_fib_for_uris()`: FIB computation for specific URI-to-publisher mappings
- `build_graph_and_subnets()`: Converts mesh_links to adjacency graph and LinkSubnet list

**Network Configuration (runtime/net_config.py):**
- `apply_ip_addr()`: Assigns /24 subnets per link
- `apply_fib()` / `apply_fib_for_uris()`: Applies computed routes via Mininet

**Template Management (runtime/template.py):**
- `ensure_node_dirs()`: Creates host directories from templates using `assign_roles()`
- `cleanup_node_dirs()`: Removes dynamically generated host directories
- `update_local_sock_id()`: Modifies LOCAL_SOCK_ID to avoid socket conflicts

### Disaster Topology Features

**Host Failure Simulation:**
```bash
--down-interval <sec>    # Interval between down/up cycles
--down-duration <sec>    # Time to keep hosts down
--down-count <n>         # Number of hosts to down per cycle
--down-stagger <sec>     # Offset between individual host downs
--down-exclude <ids>     # Host IDs to exclude (comma-separated)
```

**Bandwidth Control (runtime/bandwidth.py):**
```bash
--bw nodeA,nodeB,mbps    # Set link bandwidth (repeatable)
```

**External Interface (runtime/bridge.py):**
```bash
--ext host,ifname[,ip][,mtu]   # Attach external interface to host
```

**JSON/YAML Configuration:**

Basic JSON example with multiple publishers:
```json
{
  "hosts": 10,
  "switches": 15,
  "seed": 42,
  "puts": [
    {"host": 9, "uri": "ccnx:/test/video1", "file": "./video.bin"},
    {"host": 7, "uri": "ccnx:/test/data1", "file": "./data.bin"}
  ],
  "gets": [
    {"host": 0, "uri": "ccnx:/test/video1"},
    {"host": 1, "uri": "ccnx:/test/data1"}
  ]
}
```

YAML example with auto-generation:
```yaml
hosts: 10
switches: 15
seed: 42
auto:
  publishers: [9]
  consumers: "random:5"
  content_count: 3
  uri_prefix: "ccnx:/test"
  consumer_per_content: 2
```

**Topology PNG Output:**
```bash
--topo-png output.png           # Output path
--topo-layout spring            # Layout: spring, kamada_kawai, circular
```

## Runtime Artifacts

After running scenarios, the following files appear:

- `hN-cefnetd-log` - Forwarding daemon logs for host N
- `hN-csmgrd-log` - Cache manager logs for router hosts
- `cefputfile_*.log` - Publisher operation logs
- `cefgetfile_*.log` - Consumer operation logs
- `recvfile_at_hN` - Retrieved content files
- `*.png` - Topology visualization images (when --topo-png used)
- `meta.json` - Experiment metadata (disaster scenario with --run-dir)
- `script.log` - Full script output log (disaster scenario)

## Common Modifications

**Adding a new host role:**
Modify `assign_roles()` in `src/core/roles.py` to add new `NodeRole` constants and assignment logic.

**Changing content URI:**
Update the `ccnx:/test` prefix in FIB computation (`core/fib.py`) or use `--config` with custom `puts`/`gets` in disaster topology.

**Adjusting cache behavior:**
Edit `configs/templates/h1/csmgrd.conf` template (applies to all router nodes).

**Testing link failures:**
- Use disaster topology with `--down-*` options for automated failure simulation
- Programmatically use `runtime/links.py:set_node_links_state()`

**Adding a new scenario:**
1. Create a new class extending `BaseScenario` in `src/scenarios/`
2. Implement `build_topology()`, `configure()`, `run_experiment()`, `teardown()`
3. Add a subcommand in `src/cli/main.py`

## Development

**Package management:**
```bash
uv sync              # Install dependencies
uv run python3 ...   # Run with managed environment
```

## Notice
Separate functions into separate files by type, and do not recreate existing functions in the execution script. If you need to edit them, edit the existing function and check that the modifications have been made.
Make functions as flexible as possible by using variables.

**Dependencies:**
- mininet>=2.3.0
- networkx>=3.6.1 (for topology algorithms and PNG output)
- matplotlib>=3.10.8 (for PNG output)
- pyyaml>=6.0 (for YAML configuration support)

## Security Notes

- `configs/templates/h*/default-private-key` files contain sensitive cryptographic material - do not commit changes or share
- All scripts require root privileges due to Mininet's network namespace manipulation
- Only run in trusted/isolated environments (VMs recommended)
