"""Core domain layer (pure Python, no Mininet dependency)."""

from .graph import (
    UnionFind,
    compute_distances,
    dijkstra_all,
    k_shortest_paths,
    path_cost,
    select_k_centers,
    shortest_path,
)
from .fib import LinkSubnet, compute_fib, compute_fib_for_uris
from .flap_state import FlapState
from .paths import ROOT_DIR, TEMPLATE_ROOT, resolve_run_dir
from .roles import CONSUMER, PUBLISHER, ROUTER, NodeRole, assign_roles

__all__ = [
    # graph
    "UnionFind",
    "shortest_path",
    "dijkstra_all",
    "path_cost",
    "k_shortest_paths",
    "compute_distances",
    "select_k_centers",
    # fib
    "LinkSubnet",
    "compute_fib",
    "compute_fib_for_uris",
    # flap_state
    "FlapState",
    # paths
    "ROOT_DIR",
    "TEMPLATE_ROOT",
    "resolve_run_dir",
    # roles
    "NodeRole",
    "CONSUMER",
    "ROUTER",
    "PUBLISHER",
    "assign_roles",
]
