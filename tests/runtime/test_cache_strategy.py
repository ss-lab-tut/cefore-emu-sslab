"""CacheStrategy contract: KCenters / RandomCSMode / Roles each return set[int].

The strategies own the "which hosts run csmgrd?" decision plus any side effects
(RandomCSMode writes per-host CS_MODE files via apply_cs_modes). The seam in
scenario_setup.py treats them polymorphically: scenario chooses a Strategy,
seam calls .place(ctx) -> set[int].
"""

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from src.runtime.cache_strategy import (
    CacheContext,
    KCentersStrategy,
    RandomCSModeStrategy,
    RolesCacheStrategy,
)


# -- KCentersStrategy --------------------------------------------------------

def test_kcenters_strategy_delegates_to_cache_placement(monkeypatch):
    captured = {}

    class FakePlacement:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def place(self):
            captured["placed"] = True
            return {0, 2, 4}

    monkeypatch.setattr("src.runtime.cache_strategy.CachePlacement", FakePlacement)
    strategy = KCentersStrategy(
        cache_config={"strategy": "k_centers"},
        cache_count=3,
        down_count=1,
        exclude_publishers=True,
        cache_default_rct_ms=500,
    )
    ctx = CacheContext(host_count=6, host_graph={"a": []}, publisher_ids={5})
    result = strategy.place(ctx)

    assert result == {0, 2, 4}
    assert captured["placed"] is True
    kw = captured["kwargs"]
    assert kw["host_count"] == 6
    assert kw["host_graph"] == {"a": []}
    assert kw["publisher_ids"] == {5}
    assert kw["cache_config"] == {"strategy": "k_centers"}
    assert kw["cache_count"] == 3
    assert kw["down_count"] == 1
    assert kw["exclude_publishers"] is True
    assert kw["cache_default_rct_ms"] == 500


def test_kcenters_strategy_defaults_match_cache_placement():
    # Defaults must mirror CachePlacement's so a scenario passing no extras
    # gets behavior identical to the pre-refactor literal call.
    s = KCentersStrategy()
    assert s.cache_config is None
    assert s.cache_count == 0
    assert s.down_count == 0
    assert s.exclude_publishers is True
    assert s.cache_default_rct_ms is None


# -- RandomCSModeStrategy ----------------------------------------------------

def test_random_cs_mode_strategy_assigns_modes_and_returns_mode2_hosts(monkeypatch):
    derive_calls = []
    assign_calls = []
    apply_calls = []

    def fake_derive(seed, name):
        derive_calls.append((seed, name))
        return 12345

    def fake_assign(host_range, publisher_ids, rng):
        assign_calls.append((tuple(host_range), set(publisher_ids), rng))
        # h0 -> mode 0, h1 publisher -> mode 2, h2 -> mode 2, h3 -> mode 1
        return {0: 0, 1: 2, 2: 2, 3: 1}

    def fake_apply(cs_modes):
        apply_calls.append(dict(cs_modes))

    monkeypatch.setattr("src.runtime.cache_strategy.derive_seed", fake_derive)
    monkeypatch.setattr("src.runtime.cache_strategy.assign_random_cs_modes", fake_assign)
    monkeypatch.setattr("src.runtime.cache_strategy.apply_cs_modes", fake_apply)

    strategy = RandomCSModeStrategy(seed=42)
    ctx = CacheContext(host_count=4, host_graph=None, publisher_ids={1})
    result = strategy.place(ctx)

    # Side effect: apply_cs_modes called with the assigned map.
    assert apply_calls == [{0: 0, 1: 2, 2: 2, 3: 1}]
    # Derived seed used "cs-mode" subkey.
    assert derive_calls == [(42, "cs-mode")]
    # Host range passed to assigner = range(host_count).
    assert assign_calls[0][0] == tuple(range(4))
    assert assign_calls[0][1] == {1}
    # Returned set = hosts whose mode == 2.
    assert result == {1, 2}


# -- RolesCacheStrategy ------------------------------------------------------

@dataclass
class _Role:
    runs_csmgrd: bool


def test_roles_strategy_returns_csmgrd_running_hosts():
    roles = {
        0: _Role(runs_csmgrd=True),
        1: _Role(runs_csmgrd=False),
        2: _Role(runs_csmgrd=True),
        3: _Role(runs_csmgrd=False),
    }
    strategy = RolesCacheStrategy(roles=roles)
    ctx = CacheContext(host_count=4, host_graph=None, publisher_ids=set())

    assert strategy.place(ctx) == {0, 2}


def test_roles_strategy_handles_missing_role_entries():
    # Defensive: if a host index has no role entry, it does not run csmgrd.
    roles = {0: _Role(runs_csmgrd=True)}
    strategy = RolesCacheStrategy(roles=roles)
    ctx = CacheContext(host_count=3, host_graph=None, publisher_ids=set())

    assert strategy.place(ctx) == {0}
