"""Unit tests for MeshScenario / LinearScenario constructor-time validation.

MeshScenario.__init__ and LinearScenario.__init__ both call sys.exit(...) when
given nonsensical topology parameters, instead of raising a domain exception.
argparse-style CLIs treat sys.exit as "print message, stop" -- but that means
the checks are otherwise untested: nothing here exercises them via pytest.raises
before this file. Each test below pins one specific guard by choosing the one
invalid argument that trips it while every other argument stays inside the
valid range, so a guard being accidentally removed or reordered surfaces as a
distinct test failure rather than a single catch-all.

Note: MeshScenario.__init__ creates `run_dir` (via `run_dir.mkdir(...)`)
*before* running any of its validation checks (mesh.py mkdir at line 59,
validation starts at line 65). Every MeshScenario construction below therefore
passes `run_dir=tmp_path` so no directories are ever created in the repo tree.
"""

import pytest

from src.scenarios.linear import LinearScenario
from src.scenarios.mesh import MeshScenario


class TestMeshScenarioInitValidation:
    """One test per sys.exit guard in MeshScenario.__init__, in source order."""

    def test_host_num_below_three_exits(self, tmp_path):
        """host_num is the first guard checked; 2 hosts cannot form a mesh."""
        with pytest.raises(SystemExit):
            MeshScenario(
                host_num=2,
                swhich_num=2,
                seed=1,
                k_paths=1,
                run_dir=tmp_path,
            )

    def test_k_paths_below_one_exits(self, tmp_path):
        """k_paths=0 would ask cefroute to program zero FIB paths."""
        with pytest.raises(SystemExit):
            MeshScenario(
                host_num=3,
                swhich_num=2,
                seed=1,
                k_paths=0,
                run_dir=tmp_path,
            )

    def test_swhich_num_below_two_exits(self, tmp_path):
        """swhich_num=1 cannot even connect a 2-host pair, let alone a mesh."""
        with pytest.raises(SystemExit):
            MeshScenario(
                host_num=3,
                swhich_num=1,
                seed=1,
                k_paths=1,
                run_dir=tmp_path,
            )

    def test_swhich_num_above_max_possible_links_exits(self, tmp_path):
        """max_possible_links(3) == 3 (complete graph); 4 exceeds it."""
        with pytest.raises(SystemExit):
            MeshScenario(
                host_num=3,
                swhich_num=4,
                seed=1,
                k_paths=1,
                run_dir=tmp_path,
            )

    def test_swhich_num_below_min_required_links_exits(self, tmp_path):
        """min_required_links(5) == 4 (spanning tree); 3 leaves a host stranded.

        host_num=5 keeps this above the swhich_num<2 guard (3 >= 2) and below
        the max_possible_links guard (max_possible_links(5) == 10), so this is
        the only guard 3 can trip for a 5-host mesh.
        """
        with pytest.raises(SystemExit):
            MeshScenario(
                host_num=5,
                swhich_num=3,
                seed=1,
                k_paths=1,
                run_dir=tmp_path,
            )


class TestLinearScenarioInitValidation:
    """The sole sys.exit guard in LinearScenario.__init__."""

    def test_host_num_below_two_exits(self, tmp_path):
        """A linear topology needs at least 2 hosts to form h0-s0-h1."""
        with pytest.raises(SystemExit):
            LinearScenario(host_num=1, run_dir=tmp_path)
