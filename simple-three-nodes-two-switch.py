#!/usr/bin/env python

"""
This is a simple example using 3 nodes running Cefore (Consumer, Router, Publisher). 
"""

from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo

from mininet.util import irange
from mininet.log import info

import time

### Topology
# h0 <---s0---> h1 <---s1---> h2
# h0: consumer
# h1: router
# h2: publisher
# s0, s1: switch

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
        command = "cefroute add ccnx:/test udp 192.168.0.2 -d ./" + nodeName
        print(nodeName, "command:", command)
        info( net.hosts[id].cmd(command) )
      else: # h1
        command = "cefroute add ccnx:/test udp 192.168.1.3 -d ./" + nodeName
        print(nodeName, "command:", command)
        info( net.hosts[id].cmd(command) )

def runSimpleLink():
    "Create and run simple link network"
    hostNum = 3
    topo = simpleLinkTopo( n=hostNum )
    net = Mininet( topo=topo, waitConnected=True )
    net.start()

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
      command = "cefnetdstart -d ./" + nodeName + " > " + nodeName + "-cefnetd-log"
      print(nodeName, "command:", command)
      info( net.hosts[id].cmd(command) )
      time.sleep(1)

    # Create Fib of h0 and h1
    setFib( net, hostNum )
    time.sleep(1)

    # Exec cefputfile at h1
    nodeName = "h2"
    command = "cefputfile ccnx:/test -f ./sample-putfile -t 3000 -e 3000 -d ./" + nodeName  + " > cefputfile-log"
    print(nodeName, "command:", command)
    net.hosts[2].cmd(command)
    time.sleep(5) # need to wait for cefputfile to be completed 
    
    # Exec cefgetfile at h0
    nodeName = "h0"
    command = "cefgetfile ccnx:/test -f ./recvfile_at_h0 -d ./" + nodeName  + " > cefgetfile-log"
    print(nodeName, "command:", command)
    net.hosts[0].cmd(command)


    CLI( net )
    
    # Stop cefnetd at h0 and h1
    for id in irange( 0, (hostNum-1) ):
     command = "cefnetdstop -d ./h" + str(id)
     info("hosts[", id, "]:", command, "\n")
     net.hosts[id].cmd(command)

    net.stop()

class simpleLinkTopo( Topo ):
    "Simple topology with linear links"

    # pylint: disable=arguments-differ
    def build( self, n, **_kwargs ):
        hosts = [ self.addHost( 'h%s' % h ) for h in irange( 0, (n-1) ) ]        
        s0 = self.addSwitch( 's0' )
        s1 = self.addSwitch( 's1' )

        self.addLink( s0, hosts[0] )
        self.addLink( s0, hosts[1] )
        self.addLink( s1, hosts[1] )
        self.addLink( s1, hosts[2] )


if __name__ == '__main__':
    setLogLevel( 'info' )
    runSimpleLink()
