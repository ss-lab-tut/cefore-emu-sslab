"""Polymorphic cache-placement strategies for ScenarioSetupSpec.

A CacheStrategy decides which hosts run csmgrd (so they appear in
``daemon_fleet.csmgrd_nodes``) and may apply side effects such as writing
per-host CS_MODE files. Each scenario picks the Strategy it needs:

- ``KCentersStrategy``: disaster (k_centers/manual/degree_based path) and
  connect (with ``exclude_publishers=False``) -- delegates to
  ``CachePlacement``.
- ``RandomCSModeStrategy``: disaster's ``cache_config.strategy == "random"``
  branch -- assigns per-host CS_MODE 0/1/2 from a derived seed and applies
  them; cache nodes are those that land on mode 2.
- ``RolesCacheStrategy``: mesh -- ``csmgrd`` hosts come from
  ``assign_roles`` (no graph-based placement, no CS_MODE write).

The setup seam passes a ``CacheContext`` snapshot (host_count, host_graph,
publisher_ids); strategies ignore fields they do not need (e.g.
RolesCacheStrategy never reads host_graph).
"""

import random
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.roles import assign_random_cs_modes, derive_seed
from .cache_manager import CachePlacement
from .template import apply_cs_modes


@dataclass(frozen=True)
class CacheContext:
    """Snapshot of scenario state available to every Strategy."""
    host_count: int
    host_graph: Any  # dict from build_host_graph; None when strategy does not need it
    publisher_ids: set[int]


class CacheStrategy(Protocol):
    """Decide which hosts run csmgrd as cache nodes."""

    def place(self, ctx: CacheContext) -> set[int]: ...


@dataclass
class KCentersStrategy:
    """Graph-based placement via CachePlacement (k_centers / manual / degree_based).

    Defaults mirror ``CachePlacement.__init__`` so an instance with no
    constructor args produces behavior identical to the pre-refactor literal
    ``CachePlacement(host_count=..., host_graph=..., publisher_ids=...)``
    call.
    """

    cache_config: dict | None = None
    cache_count: int = 0
    down_count: int = 0
    exclude_publishers: bool = True
    cache_default_rct_ms: int | None = None

    def place(self, ctx: CacheContext) -> set[int]:
        return CachePlacement(
            host_count=ctx.host_count,
            host_graph=ctx.host_graph,
            publisher_ids=ctx.publisher_ids,
            cache_config=self.cache_config,
            cache_count=self.cache_count,
            down_count=self.down_count,
            exclude_publishers=self.exclude_publishers,
            cache_default_rct_ms=self.cache_default_rct_ms,
        ).place()


@dataclass
class RandomCSModeStrategy:
    """Per-host random CS_MODE 0/1/2 with mode-2 hosts treated as caches.

    Publishers always receive mode 1 or 2 (need cache to avoid content
    vanishing); other hosts receive mode 0/1/2 uniformly. ``apply_cs_modes``
    writes the assignment to each host's csmgrd.conf as a side effect.
    """

    seed: Any

    def place(self, ctx: CacheContext) -> set[int]:
        rng = random.Random(derive_seed(self.seed, "cs-mode"))
        cs_modes = assign_random_cs_modes(
            range(ctx.host_count), ctx.publisher_ids, rng,
        )
        apply_cs_modes(cs_modes)
        return {idx for idx, mode in cs_modes.items() if mode == 2}


@dataclass
class RolesCacheStrategy:
    """Cache set derived from pre-computed ``assign_roles`` output (mesh)."""

    roles: dict

    def place(self, ctx: CacheContext) -> set[int]:
        return {
            idx for idx in range(ctx.host_count)
            if self.roles.get(idx) is not None and self.roles[idx].runs_csmgrd
        }
