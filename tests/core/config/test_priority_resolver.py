"""Tests for src.core.config.priority_resolver."""

from src.core.config.priority_resolver import PriorityConfigManager


def _make_manager(**kwargs):
    config = {
        "high": {
            "patterns": ["ccnx:/test/video*"],
            "mode": "putget",
            "expiry": 5000,
            "cache_time": 3000,
            "rate": 10,
            "pipeline": 4,
            "valid_algo": "crc32c",
            **kwargs,
        }
    }
    return PriorityConfigManager(config)


def test_empty_manager():
    mgr = PriorityConfigManager()
    level, config = mgr.resolve_priority("ccnx:/test/anything")
    assert level is None
    assert config is None


def test_exact_match():
    mgr = PriorityConfigManager({"p": {"patterns": ["ccnx:/test/exact"]}})
    level, _ = mgr.resolve_priority("ccnx:/test/exact")
    assert level == "p"


def test_wildcard_match():
    mgr = _make_manager()
    level, config = mgr.resolve_priority("ccnx:/test/video1")
    assert level == "high"
    assert config["expiry"] == 5000


def test_no_match():
    mgr = _make_manager()
    level, config = mgr.resolve_priority("ccnx:/other/data")
    assert level is None


def test_apply_to_put_putget():
    mgr = _make_manager()
    op = {"uri": "ccnx:/test/video1", "host": 0}
    result = mgr.apply_to_put(op)
    assert result["expiry"] == 5000
    assert result["cache_time"] == 3000
    assert result["rate"] == 10


def test_apply_to_put_no_override():
    mgr = _make_manager()
    op = {"uri": "ccnx:/test/video1", "host": 0, "expiry": 9999}
    result = mgr.apply_to_put(op)
    assert result["expiry"] == 9999  # not overridden


def test_apply_to_get():
    mgr = _make_manager()
    op = {"uri": "ccnx:/test/video1", "host": 0}
    result = mgr.apply_to_get(op)
    assert result["pipeline"] == 4
    assert result["valid_algo"] == "crc32c"


# ── pubsub mode ──


def _make_pubsub_manager():
    config = {
        "live": {
            "patterns": ["ccnx:/live/*"],
            "mode": "pubsub",
            "expiry": 1000,
            "cache_time": 2000,
            "rate": 5,
            "block_size": 512,
            "lifetime": 3000,
            "retry_limit": 3,
            "target": "trg",
            "ti_valid_algo": "crc32c",
            "rd_valid_algo": "rsa-sha256",
            "port_num": 9696,
            "pipeline": 8,
            "ri_valid_algo": "crc32c",
            "td_valid_algo": "rsa-sha256",
        }
    }
    return PriorityConfigManager(config)


def test_apply_to_put_pubsub():
    mgr = _make_pubsub_manager()
    op = {"uri": "ccnx:/live/stream1", "host": 0, "mode": "pubsub"}
    result = mgr.apply_to_put(op)
    assert result["mode"] == "pubsub"
    pub_opts = result.get("pub_opts", {})
    assert pub_opts.get("expiry") == 1000
    assert pub_opts.get("cache_time") == 2000
    assert pub_opts.get("rate") == 5
    assert pub_opts.get("block_size") == 512
    assert pub_opts.get("lifetime") == 3000
    assert pub_opts.get("retry_limit") == 3
    assert pub_opts.get("target") == "trg"
    assert pub_opts.get("ti_valid_algo") == "crc32c"
    assert pub_opts.get("rd_valid_algo") == "rsa-sha256"
    assert pub_opts.get("port_num") == 9696


def test_apply_to_put_pubsub_no_override():
    mgr = _make_pubsub_manager()
    op = {
        "uri": "ccnx:/live/stream1", "host": 0, "mode": "pubsub",
        "pub_opts": {"expiry": 9999},
    }
    result = mgr.apply_to_put(op)
    assert result["pub_opts"]["expiry"] == 9999  # not overridden


def test_apply_to_get_pubsub():
    mgr = _make_pubsub_manager()
    op = {"uri": "ccnx:/live/stream1", "host": 0, "mode": "pubsub"}
    result = mgr.apply_to_get(op)
    assert result["mode"] == "pubsub"
    sub_opts = result.get("sub_opts", {})
    assert sub_opts.get("pipeline") == 8
    assert sub_opts.get("ri_valid_algo") == "crc32c"
    assert sub_opts.get("td_valid_algo") == "rsa-sha256"
    assert sub_opts.get("port_num") == 9696


def test_apply_to_put_no_uri():
    mgr = _make_manager()
    op = {"host": 0}
    result = mgr.apply_to_put(op)
    assert result == op


def test_apply_to_get_no_uri():
    mgr = _make_manager()
    op = {"host": 0}
    result = mgr.apply_to_get(op)
    assert result == op


def test_apply_sets_mode_from_config():
    """When operation has no mode, config mode is applied."""
    mgr = _make_pubsub_manager()
    op = {"uri": "ccnx:/live/stream1", "host": 0}
    result = mgr.apply_to_put(op)
    assert result["mode"] == "pubsub"


def test_pattern_string_not_list():
    """patterns as a single string instead of list."""
    config = {"p": {"patterns": "ccnx:/single"}}
    mgr = PriorityConfigManager(config)
    level, _ = mgr.resolve_priority("ccnx:/single")
    assert level == "p"
