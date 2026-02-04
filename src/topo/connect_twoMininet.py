#!/usr/bin/env python

import sys
import re

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.log import lg, info
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, Controller, Node
from mininet.topo import Topo
from mininet.util import irange

Network_VM_Hosts = '192.168.201.0/24'

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
    info( '*** Adding routes in this vm-host: route add -net ' + routes + ' dev ' + str(intf) + '\n' )
    root.cmd( 'route add -net ' + routes + ' dev ' + str( intf ) )

def ExecuteOneMininet( hostCount, h1_ip, routes, routes2, ip_anotherVM, no_cli=False ):

    # Make a topology
    topo = MakeTopo( hostCount )
    # Make the network 
    net = Mininet( topo=topo, waitConnected=True ) 
    # Set h1's ip addr
    h1 = net.get('h1')
    h1.setIP( h1_ip )
    # Determine ip addr of a node in root namespace (Assume that the prefix of 'routes' is '/24')
    tmp_list_routes =  ( re.split('[./]', routes) )
    ip_root = tmp_list_routes[0] + '.' + tmp_list_routes[1] + '.' + tmp_list_routes[2] + '.111' 
    # One switch (s0) through which Mininet hosts connect to root namespace
    switch = net[ 's0' ]
    ConnectToRootNS( net, switch, ip_root, routes ) 

    # Add routes from h1 to vm-hosts
    info( '*** Adding routes in h1: route add -net ' + Network_VM_Hosts + ' gw ' + ip_root + '\n')
    h1.cmd( 'route add -net ' + Network_VM_Hosts + ' gw ' + ip_root )

    # Add routes from h1 to another Mininet 
    info( '*** Adding routes in h1: route add -net ' + routes2 + ' gw ' + ip_root + '\n')
    h1.cmd( 'route add -net ' + routes2 + ' gw ' + ip_root )

    # Add routes from this vm-host to Mininet hosts on another vm-host 
    root = Node( 'root', inNamespace=False ) 
    info( '*** Adding routes in this vm-host: route add -net ' + routes2 + ' gw ' + ip_anotherVM + '\n')
    root.cmd( 'route add -net ' + routes2 + ' gw ' + ip_anotherVM )
    
    net.start()
    if not no_cli:
        CLI( net )

    # Delete routes from this vm-host to Mininet hosts on another vm-host
    info( '*** Deleting routes in this vm-host: route add -net ' + routes2 + '\n')
    root.cmd( 'route del -net ' + routes2 )

    net.stop()
    mn_cleanup()

if __name__ == '__main__':
    lg.setLogLevel( 'info' )

    no_cli = "--no-cli" in sys.argv
    if no_cli:
        sys.argv.remove("--no-cli")

    if len( sys.argv ) > 4:
        h1_ip = sys.argv[1]
        route_to_thisMininet = sys.argv[2]
        route_to_anotherMininet = sys.argv[3]
        ip_anotherVM = sys.argv[4]
    else:
        info( "Pleaes specify 1) an ip address of h1(the Mininet-host) as the first argument\n")
        info( "               2) routes to this Mininet host networks as the second argument\n")
        info( "               3) routes to another Mininet host networks running on another vm-host, as the third argument\n")
        info( "               4) the ip address of another vm-host as the forth argument\n")
        info( "(Ex. for VM-1) $ sudo python3 ./xxxx.py 10.0.1.1/24 10.0.1.0/24 10.0.2.0/24 192.168.201.62\n")
        info( "(Ex. for VM-2) $ sudo python3 ./xxxx.py 10.0.2.1/24 10.0.2.0/24 10.0.1.0/24 192.168.201.122\n")
        exit()

    info( "*** Arguments:\nh1's ip_addr is", h1_ip, '\n' )
    info( "route_to_thisMininet:", route_to_thisMininet, '\n' )
    info( "route_to_anotherMininet:", route_to_anotherMininet, '\n' )
    info( "ip_anotherVM:", ip_anotherVM, '\n' )
    ExecuteOneMininet( 1, h1_ip, route_to_thisMininet, route_to_anotherMininet, ip_anotherVM, no_cli=no_cli )
