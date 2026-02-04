"""
This is a simple example that demonstrates cefsubfile/cefpubfile using three nodes.
"""

import sys
import time

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.util import irange

### Topology and ip addrs
# h0 <---s0---> h1 <---s1---> h2
# h0-ip: 192.168.0.1/24
# h1-ip: 192.168.0.2/24
# h1-ip: 192.168.1.2/24
# h2-ip: 192.168.1.3/24
def setIpAddr( net, hostNum ):
    # Set the ip addr of each host
    for id in irange( 0, (hostNum-1) ):
      nodeName = "h" + str(id)
      if nodeName == "h0":
        command = "ifconfig " + nodeName + "-eth0 " + "192.168.0.1"
        print(nodeName, "command:", command)
        net.hosts[id].cmd(command)
      elif nodeName == "h1":
        command = "ifconfig " + nodeName + "-eth0 " + "192.168.0.2"
        print(nodeName, "command:", command)
        net.hosts[id].cmd(command)
        command = "ifconfig " + nodeName + "-eth1 " + "192.168.1.2"
        print(nodeName, "command:", command)
        net.hosts[id].cmd(command)
      else : # h2
        command = "ifconfig " + nodeName + "-eth0 " + "192.168.1.3"
        print(nodeName, "command:", command)
        net.hosts[id].cmd(command)

def setFib( net, hostNum):
    # Set fib of h0 and h1 
    for id in irange( 0, (hostNum-2) ):
      nodeName = "h" + str(id)
      if nodeName == "h0":
        command = "cefroute add ccnx:/test1 udp 192.168.0.2 -d ./" + nodeName
        print(nodeName, "command:", command)
        info( net.hosts[id].cmd(command) )
        time.sleep(1)
        command = "cefroute add ccnx:/test2 udp 192.168.0.2 -d ./" + nodeName
        print(nodeName, "command:", command)
        info( net.hosts[id].cmd(command) )
      else: # h1
        command = "cefroute add ccnx:/test1 udp 192.168.1.3 -d ./" + nodeName
        print(nodeName, "command:", command)
        info( net.hosts[id].cmd(command) )
        time.sleep(1)
        command = "cefroute add ccnx:/test2 udp 192.168.1.3 -d ./" + nodeName
        print(nodeName, "command:", command)
        info( net.hosts[id].cmd(command) )

def runSimpleLink():
    "Create and run simple link network"
    no_cli = "--no-cli" in sys.argv
    hostNum = 3
    topo = simpleLinkTopo( n=hostNum )
    net = Mininet( topo=topo, link=TCLink, waitConnected=True )
    net.start()

    #print("net.hosts[0]", net.hosts[0]) # --> h0
    #h0 = net.get('h0')

    # Set ip addr of each host
    setIpAddr( net, hostNum)

    # Check ifconfig-result at h0, h1 and h2
    for id in irange( 0, (hostNum-1) ):
      #result = net.hosts[id].cmd("ifconfig")
      #info("hosts[", id, "]-ifconfig:", "\n", result)
      nodeName = "h" + str(id)
      print(nodeName, "command:", "ifconfig")
      info( net.hosts[id].cmd("ifconfig") )

    # Launch cefnetd at h0, h1 and h2
    for id in irange( 0, (hostNum-1) ):
      nodeName = "h" + str(id)
      command = "cefnetdstart -d ./" + nodeName + " > " + nodeName + "-cefnetd-log &"
      print(nodeName, "command:", command)
      info( net.hosts[id].cmd(command) )
      time.sleep(1)

    # Create Fib of h0 and h1
    setFib( net, hostNum )

    # Exec cefsubfile at h2
    time.sleep(1)
    nodeName = "h2"
    command = "cefsubfile ccnx:/test1 -s 32 -d ./" + nodeName  + " > cefsubfile-log &"
    print(nodeName, "command:", command)
    net.hosts[2].cmd(command)

    time.sleep(3)	
    
    # Exec cefpubfile at h0
    nodeName = "h0"
    command = "cefpubfile ccnx:/test1 -f ./sample-putfile-30M -b 8000 -r 1000 -t 3000 -e 3000 -d ./" + nodeName  + " > cefpubfile-log &"
    print(nodeName, "command:", command)
    net.hosts[0].cmd(command)
    
    time.sleep(10)	

    if not no_cli:
        CLI( net )

    # Stop cefnetd at h0 and h1
    for id in irange( 0, (hostNum-1) ):
     command = "cefnetdstop -d ./h" + str(id)
     info("hosts[", id, "]:", command, "\n")
     net.hosts[id].cmd(command)
     time.sleep(2)

    net.stop()
    mn_cleanup()

class simpleLinkTopo( Topo ):
    "Simple topology with linear links"

    # pylint: disable=arguments-differ
    def build( self, n, **_kwargs ):
        #h1, h2 = self.addHost( 'h1' ), self.addHost( 'h2' )
        hosts = [ self.addHost( 'h%s' % h ) for h in irange( 0, (n-1) ) ]        
        s0 = self.addSwitch( 's0' )
        s1 = self.addSwitch( 's1' )

        """
        self.addLink( s0, hosts[0], bw=500, delay="2ms", loss=0, use_htb=True)
        self.addLink( s0, hosts[1], bw=500, delay="2ms", loss=0, use_htb=True)
        self.addLink( s1, hosts[1], bw=500, delay='2ms', loss=0, use_htb=True)
        self.addLink( s1, hosts[2], bw=500, delay='2ms', loss=0, use_htb=True)
        """
        
        """
        #self.addLink( s0, hosts[0], delay="2ms", loss=0, use_htb=True)
        self.addLink( s0, hosts[0])
        self.addLink( s0, hosts[1], delay="2ms", loss=0, use_htb=True)
        #self.addLink( s1, hosts[1], delay='2ms', loss=0, use_htb=True)
        self.addLink( s1, hosts[1])
        self.addLink( s1, hosts[2], delay='2ms', loss=0, use_htb=True)
        """

        self.addLink( s0, hosts[0])
        self.addLink( s0, hosts[1])
        self.addLink( s1, hosts[1])
        self.addLink( s1, hosts[2])



if __name__ == '__main__':
    setLogLevel( 'info' )
    runSimpleLink()
