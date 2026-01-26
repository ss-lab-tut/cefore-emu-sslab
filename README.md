# CeforeEmu (Simple ver.)
## Overview
CeforeEmu is a network emulator based on Mininet, which can be run on Ubuntu 22.04. CeforeEmu creates a virtual network topology with virtual hosts where Cefore daemons (*cefnetd*) can be launched. The simple script (simple-three-nodes-two-switch.py) launches three Cefore nodes (h0:consumer, h1:router, h2:publisher), which are linearly connected. In this scenario, the publisher node executes *cefputfile* to input the sample-putfile into the local cache, and then, the consumer tries to download the file by executing *cefgetfile*.

Mesh scripts are also available:
- `mesh-nodes-switches.py`: random host-to-host mesh with multi-path FIB.
- `mesh-disaster-topology.py`: periodic host down/up + bandwidth control + external interface attach, with repeated `cefgetfile` logging.

## How to Run 
### Required Task before Starting
* Install Cefore into your Ubuntu (22.04) environment.
* Install Mininet (version 2.3.0) into your Ubuntu environment.
  (please see https://mininet.org/)
* Download and extract the CeforeEmu archive in your working directory.

### How to Start and Finish
* Run the python script:

  `sudo python3 simple-three-nodes-two-switch.py`
* Enter *exit* command, after finishing the processing:
  
  `mininet> exit`

* Run the other script:

  `sudo python3 five-node-two-switches.py --hosts 7`

Finally, you can check the log files of *cefputfile*, *cefgetfile* and *cefnetd*, which are created in the directory after finishing the processing.

If you want to change the Cefore configuration of each node, please modify the configure file under each directory (h0, h1, and h2).

## Mesh Topology Scripts
### mesh-nodes-switches.py
Random mesh of hosts connected by switches. Each destination host hX maps to prefix `ccnx:/test/example{X+1}` and uses k-shortest paths for FIB.

Run with options:
```
sudo python3 mesh-nodes-switches.py --help
sudo python3 mesh-nodes-switches.py --hosts 8 --switches 12 --seed 5 --k 3
```

Key options:
- `--hosts`: number of hosts
- `--switches`: number of random links (min: 2, max: all pairs)
- `--seed`: random seed for deterministic topology
- `--k`: number of shortest paths per destination

### mesh-disaster-topology.py
Adds periodic host down/up, optional bandwidth limits, external interface attachment, and repeated `cefgetfile` logging.

Run with options:
```
sudo python3 mesh-disaster-topology.py --help
sudo python3 mesh-disaster-topology.py --hosts 8 --switches 12 --seed 5 --k 2 \
  --down-interval 20 --down-duration 15 --down-count 3 --down-stagger 3 \
  --get-interval 10
```

Key options:
- `--down-interval`: seconds between down events (0 to disable)
- `--down-duration`: seconds to keep host down
- `--down-count`: number of hosts down per cycle
- `--down-stagger`: seconds to stagger down events within a cycle
- `--get-interval`: seconds between `cefgetfile` runs
- `--bw nodeA,nodeB,mbps`: set bandwidth on a link (repeatable)
- `--ext host,ifname[,ip][,mtu]`: attach external interface to a host (repeatable)

Logs:
- `cefputfile_{hosts}_{switches}_{seed}_{down-interval}_{down-duration}_{downhost}.log`
- `cefgetfile_{hosts}_{switches}_{seed}_{down-interval}_{down-duration}_{downhost}_hX.log`
