#!/usr/bin/env python

import sys
import re

from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import lg, info
from mininet.node import OVSKernelSwitch, Controller, Node
from mininet.topo import Topo
from mininet.util import irange

class MakeTopo( Topo ):

    def build( self, N ):
        # Create hosts and one switche
        hosts = [ self.addHost( 'h%s' % h )
                  for h in irange( 1, N ) ]
        switches = [ self.addSwitch( "s0" ) ]

        # Wire up hosts
        self.addLink( hosts[ 0 ], switches[ 0 ] )
        #self.addLink( 'h1', 's0' )
        for host in hosts[ 1: ] :
            self.addLink( host, switches[ 0 ] )

def ConnectToRootNS( network, switch, ip, routes ):

    """Connect Mininet hosts to root namespace via switch.
      network: Mininet() network object
      switch: switch to connect to root namespace
      ip: IP address for root namespace node
      routes: Mininet host networks to route to"""
    # Create a node in root namespace and link to switch 0 (s0)
    root = Node( 'root', inNamespace=False )
    intf = network.addLink( root, switch ).intf1
    root.setIP( ip, intf=intf )

    # Add routes from root ns (this vm-host) to hosts
    #info( '*** Adding routes in this vm-host: route add -net ' + routes + ' dev ' + str(intf) + '\n' )
    #root.cmd( 'route add -net ' + routes + ' dev ' + str( intf ) )

def ExecuteOneMininet( hostCount, h1_ip, routes ):

    # Make a topology
    topo = MakeTopo( hostCount )
    # Make the network
    net = Mininet( topo=topo, waitConnected=True )
    # Set h1's ip addr
    h1 = net.get('h1')
    h1.setIP( h1_ip )
    # Determine ip addr of a node in root namespace (Assume that the prefix of 'routes' is '/24')
    #tmp_list_routes =  ( re.split('[./]', routes) )
    tmp_list_routes =  ( re.split('[./]', h1_ip) )
    ip_root = tmp_list_routes[0] + '.' + tmp_list_routes[1] + '.' + tmp_list_routes[2] + '.111'
    # One switch (s0) through which Mininet hosts connect to root namespace
    switch = net[ 's0' ]
    ConnectToRootNS( net, switch, ip_root, routes )

    # Add routes from h1 to PC-host
    info( '*** Adding routes in h1: route add -net ' + routes + ' gw ' + ip_root + '\n')
    h1.cmd( 'route add -net ' + routes + ' gw ' + ip_root )


    net.start()
    CLI( net )

    # Delete routes from this vm-host to Mininet hosts on another vm-host
    #info( '*** Deleting routes in this vm-host: route add -net ' + routes2 + '\n')
    #root = Node( 'root', inNamespace=False )
    #root.cmd( 'route del -net ' + routes2 )

    net.stop()

if __name__ == '__main__':
    lg.setLogLevel( 'info' )

    if len( sys.argv ) > 2:
        h1_ip = sys.argv[1]
        Network_to_PChost = sys.argv[2]
    else:
        info( "Pleaes specify 1) an ip address of h1(the Mininet-host) as the first argument\n")
        info( "               2) routes of this VM host networks as the second argument\n")
        info( "(Example] $ sudo python3 ./xxxx.py 10.0.1.8/24 192.168.201.0/24\n")
        exit()

    info( "*** Arguments:\nh1's ip_addr is", h1_ip, '\n' )

    ExecuteOneMininet( 1, h1_ip, Network_to_PChost )
