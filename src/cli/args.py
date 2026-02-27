"""Common argparse definitions for cefore-emu CLI."""

import argparse


def add_common_args(parser):
    """Add arguments common to all topology types."""
    parser.add_argument("--hosts", type=int, default=5, help="number of hosts")
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    parser.add_argument(
        "--topo-png", type=str, default=None,
        help="write topology PNG to this path",
    )
    parser.add_argument(
        "--topo-layout", type=str, default="spring",
        help="topology layout: spring, kamada_kawai, or circular",
    )
    parser.add_argument(
        "--num", type=int, default=None,
        help="experiment number (enables log directory output)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="logs",
        help="base output directory (default: logs)",
    )
    parser.add_argument(
        "--timestamp", action="store_true",
        help="add timestamp to output directory name",
    )
    parser.add_argument(
        "--legacy", action="store_true", dest="legacy_layout",
        help="use legacy layout (output to current directory)",
    )


def add_mesh_args(parser):
    """Add arguments for mesh topology types."""
    parser.add_argument(
        "--switches", type=int, default=10,
        help="maximum number of switches to create (0 = unlimited)",
    )
    parser.add_argument(
        "--node-per-switch", type=int, default=2,
        help="max hosts per switch (0=unlimited, 2=one switch per link)",
    )
    parser.add_argument(
        "--host-degree-min", type=int, default=1,
        help="minimum number of switches per host (>=1)",
    )
    parser.add_argument(
        "--host-degree-max", type=int, default=2,
        help="maximum number of switches per host",
    )
    parser.add_argument(
        "--switch-use-all", action="store_true",
        help="create switches up to --switches and distribute extra links evenly",
    )
    parser.add_argument(
        "--k", type=int, default=2,
        help="number of shortest paths per destination",
    )


def add_disaster_args(parser):
    """Add arguments for disaster topology."""
    parser.add_argument(
        "--down-interval", type=int, default=30,
        help="seconds between down events (0 to disable)",
    )
    parser.add_argument(
        "--down-duration", type=int, default=10,
        help="seconds to keep host down",
    )
    parser.add_argument(
        "--down-exclude", type=str, default="",
        help="comma-separated host ids to exclude from flapping",
    )
    parser.add_argument(
        "--down-count", type=int, default=5,
        help="number of hosts to keep down per cycle",
    )
    parser.add_argument(
        "--down-stagger", type=int, default=2,
        help="seconds to stagger down events within a cycle",
    )
    parser.add_argument(
        "--cache-count", type=int, default=0,
        help="number of cache nodes (0 = down-count + 1)",
    )
    parser.add_argument(
        "--bw", action="append", default=[],
        help="set bandwidth: nodeA,nodeB,mbps (repeatable)",
    )
    parser.add_argument(
        "--ext", action="append", default=[],
        help="attach external intf: host,ifname[,ip][,mtu] (repeatable)",
    )
    parser.add_argument(
        "--bridge", action="append", default=[],
        help="root ns bridge: switch,root_ip,local_routes[,ext_routes,gateway] (repeatable)",
    )
    parser.add_argument(
        "--get-interval", type=int, default=10,
        help="seconds between cefgetfile runs",
    )
    parser.add_argument(
        "--config", type=str, default="",
        help="JSON/YAML config file to override parameters",
    )
    parser.add_argument(
        "--puts", type=str, default="",
        help="JSON list of put ops (host,uri,file,log)",
    )
    parser.add_argument(
        "--gets", type=str, default="",
        help="JSON list of get ops (host,uri,file,log)",
    )
    parser.add_argument(
        "--script-log", type=str, default=None,
        help="log script output to file",
    )
    parser.add_argument(
        "--no-script-log", action="store_true",
        help="disable script log output",
    )
