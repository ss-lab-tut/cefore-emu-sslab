# CeforeEmu (Simple ver.)
## Overview
CeforeEmu is a network emulator based on Mininet, which can be run on Ubuntu 22.04. CeforeEmu creates a virtual network topology with virtual hosts where Cefore daemons (*cefnetd*) can be launched. The simple script (simple-three-nodes-two-switch.py) launches three Cefore nodes (h0:consumer, h1:router, h2:publisher), which are linearly connected. In this scenario, the publisher node executes *cefputfile* to input the sample-putfile into the local cache, and then, the consumer tries to download the file by executing *cefgetfile*.

## How to Run 
### Required Task before Starting
* Install Cefore into your Ubuntu (22.04) environment.
* Install Mininet (version 2.3.0) into your Ubuntu environment.
  (please see https://mininet.org/)
* Download and extract the CeforeEmu archive in your woking directory.

### How to Start and Finish
* Run the python script:
  
  `sudo python3 simple-three-nodes-two-switchs.py`
* Enter *exit* command, after finishing the processing:
  
  `mininet> exit`


Finally, you can check the log files of *cefputfile*, *cefgetfile* and *cefnetd*, which are created in the directory after finishing the processing.

If you want to change the Cefore configuration of each node, please modify the configure file under each directory (h0, h1, and h2).
