"""Behavior tests for node directory provisioning (template.py)."""

import pytest

from src.core.roles import CONSUMER, PUBLISHER, ROUTER, NodeRole
from src.runtime.template import (
    STAMP_FILENAME,
    NodeDirError,
    _read_config_value,
    cleanup_node_dirs,
    provision_node_dirs,
)


class TestProvisionNodeDirs:
    def test_provisions_every_host_dir_under_base_dir(self, tmp_path):
        roles = {0: CONSUMER, 1: ROUTER, 2: PUBLISHER}
        generated = provision_node_dirs(roles, base_dir=tmp_path)
        assert generated == [tmp_path / "h0", tmp_path / "h1", tmp_path / "h2"]
        for idx in range(3):
            node_dir = tmp_path / f"h{idx}"
            assert (node_dir / STAMP_FILENAME).exists()
            assert (node_dir / "cefnetd.conf").exists()
        # LOCAL_SOCK_ID was rewritten per host (proves the sock-id step ran).
        conf = (tmp_path / "h1" / "cefnetd.conf").read_text()
        assert "LOCAL_SOCK_ID=1" in conf

    def test_uses_the_passed_roles_without_reassigning(self, tmp_path):
        # assign_roles would never make host 0 a PUBLISHER (idx 0 is always
        # CONSUMER). If provisioning honored the passed dict, h0 gets the
        # publisher template (CS_MODE=1), proving no internal re-derivation.
        roles = {0: PUBLISHER, 1: ROUTER}
        provision_node_dirs(roles, base_dir=tmp_path)
        assert _read_config_value(tmp_path / "h0" / "cefnetd.conf", "CS_MODE") == "1"
        assert _read_config_value(tmp_path / "h1" / "cefnetd.conf", "CS_MODE") == "2"

    def test_unmanaged_existing_dir_raises_instead_of_exiting(self, tmp_path):
        (tmp_path / "h1").mkdir()  # exists but carries no stamp
        with pytest.raises(NodeDirError, match="not created by ceforeemu"):
            provision_node_dirs({0: CONSUMER, 1: ROUTER}, base_dir=tmp_path)

    def test_missing_template_raises(self, tmp_path):
        bad = NodeRole("ghost", "no-such-template", cs_mode=0, runs_csmgrd=False)
        with pytest.raises(NodeDirError, match="missing template"):
            provision_node_dirs({0: bad}, base_dir=tmp_path)

    def test_existing_stamped_dir_is_refreshed(self, tmp_path):
        first = provision_node_dirs({0: CONSUMER}, base_dir=tmp_path)
        (tmp_path / "h0" / "stale-marker").write_text("x")
        second = provision_node_dirs({0: CONSUMER}, base_dir=tmp_path)
        assert first == second
        assert not (tmp_path / "h0" / "stale-marker").exists()
        assert (tmp_path / "h0" / STAMP_FILENAME).exists()

    def test_partial_failure_rolls_back_dirs_created_by_this_call(self, tmp_path):
        # h2 exists unmanaged -> the guard trips at idx 2, after h0/h1 were
        # created by this call. Provisioning must be atomic: remove h0/h1 and
        # leave the unmanaged h2 untouched.
        (tmp_path / "h2").mkdir()
        roles = {0: CONSUMER, 1: ROUTER, 2: PUBLISHER}
        with pytest.raises(NodeDirError):
            provision_node_dirs(roles, base_dir=tmp_path)
        assert not (tmp_path / "h0").exists()
        assert not (tmp_path / "h1").exists()
        assert (tmp_path / "h2").is_dir()
        assert not (tmp_path / "h2" / STAMP_FILENAME).exists()


class TestCleanupRoundtrip:
    def test_cleanup_removes_only_stamped_dirs(self, tmp_path):
        generated = provision_node_dirs({0: CONSUMER, 1: ROUTER}, base_dir=tmp_path)
        unmanaged = tmp_path / "h9"
        unmanaged.mkdir()  # no stamp -> must be left alone
        cleanup_node_dirs(generated + [unmanaged])
        assert not (tmp_path / "h0").exists()
        assert not (tmp_path / "h1").exists()
        assert unmanaged.is_dir()


# ---------------------------------------------------------------------------
# apply_cs_modes
# ---------------------------------------------------------------------------


class TestApplyCsModes:

    def test_writes_cs_mode_to_cefnetd_conf(self, tmp_path):
        from src.runtime.template import apply_cs_modes
        generated = provision_node_dirs(
            {0: CONSUMER, 1: ROUTER, 2: PUBLISHER}, base_dir=tmp_path,
        )
        apply_cs_modes({0: 2, 1: 0, 2: 1}, base_dir=tmp_path)
        for idx, expected in [(0, "2"), (1, "0"), (2, "1")]:
            conf = tmp_path / f"h{idx}" / "cefnetd.conf"
            text = conf.read_text()
            assert f"CS_MODE={expected}" in text
        cleanup_node_dirs(generated)

    def test_skips_missing_dirs(self, tmp_path):
        from src.runtime.template import apply_cs_modes
        # h99 doesn't exist — should not raise
        apply_cs_modes({99: 1}, base_dir=tmp_path)
