# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CeforeEmu is a network emulator based on Mininet for testing Cefore (Content-Centric Networking framework) deployments. It creates virtual network topologies with virtual hosts running Cefore daemons (cefnetd) to simulate content distribution scenarios.

**External Dependencies:**
- Cefore must be installed on Ubuntu 22.04
- Mininet version 2.3.0 must be installed
- All scripts require root privileges (sudo)

## Running Topology Scripts

**Simple 3-node linear topology (consumer-router-publisher):**
```bash
sudo python3 simple-three-nodes-two-switch.py
```

**Configurable linear topology:**
```bash
sudo python3 five-node-two-switch.py --hosts 7
```

**Configurable mesh topology:**
```bash
sudo python3 mesh-nodes-switches.py --hosts 8 --switches 12 --k 3 --seed 42
```
- `--hosts`: Number of hosts (min 3)
- `--switches`: Number of random links (min 2, max n*(n-1)/2)
- `--k`: Number of shortest paths per destination for multipath routing (default 2)
- `--seed`: Random seed for deterministic topology generation

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

### Host Configuration Directories

- `h0/`, `h1/`, `h2/` are template directories containing Cefore configuration files
- For topologies with >3 hosts, additional directories (h3, h4, ...) are generated dynamically by copying templates
- Dynamic directories are cleaned up after script completion via `cleanup_node_dirs()`

**Configuration files per host:**
- `cefnetd.conf` - Forwarding daemon config (includes LOCAL_SOCK_ID)
- `cefnetd.fib` - Static forwarding table
- `csmgrd.conf` - Cache manager config
- `conpubd.conf` - Publisher daemon config
- `plugin.conf` - Plugin configuration
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
  - Each destination gets a unique URI prefix: `ccnx:/test/exampleN`

**Dynamic Configuration:**
- `update_local_sock_id()`: Modifies LOCAL_SOCK_ID in config files to avoid socket conflicts
- `ensure_node_dirs()`: Creates host directories from templates based on role heuristics

### Mesh Topology Specifics

The mesh topology (`mesh-nodes-switches.py`) implements advanced features:

- **Multipath routing**: k-shortest paths per destination for redundancy
- **Link control**: `link_up()` and `link_down()` functions to simulate failures
- **Staggered multi-host outages**: Support for simulating multiple simultaneous link failures
- **Topology visualization**: `print_mesh_links()` renders ASCII tree view showing each host's connectivity
- **Status inspection**: `run_cefstatus()` to view FIB state
- **Deterministic generation**: `--seed` parameter for reproducible topologies
- **Publisher-aware linking**: First link always connects to publisher for guaranteed connectivity

## Runtime Artifacts

After running scripts, the following files appear in the root directory:

- `hN-cefnetd-log` - Forwarding daemon logs for host N
- `hN-csmgrd-log` - Cache manager logs for router hosts
- `cefputfile-log` - Publisher operation log
- `cefgetfile-log` - Consumer operation log
- `recvfile_at_h0` - Retrieved content file at consumer

## Common Modifications

**Adding a new host role:**
Modify `select_template()` to return appropriate template (h0, h1, or h2) based on index and host count.

**Changing content URI:**
Update the `ccnx:/test` prefix in `setFib()` or `set_fib()` and corresponding `cefputfile`/`cefgetfile` commands.

**Adjusting cache behavior:**
Edit `h1/csmgrd.conf` template (applies to all router nodes).

**Testing link failures:**
In mesh topology, uncomment the `link_down()` calls (lines 448-454) or add custom failure scenarios before `run_cefgetfile()`. Multiple simultaneous link failures can be used to test staggered multi-host outages and multipath routing resilience.

## Security Notes

- `h*/default-private-key` files contain sensitive cryptographic material - do not commit changes or share
- All scripts require root privileges due to Mininet's network namespace manipulation
- Only run in trusted/isolated environments (VMs recommended)
