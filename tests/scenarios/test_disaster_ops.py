"""Unit tests for event-only disaster operation metadata."""

from argparse import Namespace

from src.scenarios.disaster import DisasterScenario


def _make_args(**overrides):
    data = {
        "hosts": 3,
        "seed": 42,
        "events": [],
        "bridges": [],
        "bridge": [],
        "ext": [],
        "no_cli": False,
        "results_json": "",
        "addressing": {},
    }
    data.update(overrides)
    return Namespace(**data)


def test_no_events_yields_no_publishers(tmp_path):
    scenario = DisasterScenario(_make_args(), run_dir=tmp_path)
    assert scenario.publisher_ids == set()
    assert scenario.uri_publishers == {}


def test_event_publishers_drive_uri_metadata(tmp_path):
    events = [
        {
            "at": 1,
            "type": "put",
            "host": 2,
            "uri": "ccnx:/test/sample",
            "file": "./sample-putfile",
        },
        {
            "at": 2,
            "type": "pubsub_pub",
            "host": 1,
            "uri": "ccnx:/test/live",
            "file": "./sample-putfile",
        },
    ]
    scenario = DisasterScenario(_make_args(events=events), run_dir=tmp_path)
    assert scenario.publisher_ids == {1, 2}
    assert scenario.uri_publishers == {
        "ccnx:/test/sample": 2,
        "ccnx:/test/live": 1,
    }


def test_legacy_content_keys_do_not_drive_publishers(tmp_path):
    scenario = DisasterScenario(
        _make_args(
            puts=[{"host": 2, "uri": "ccnx:/test/ignored"}],
            gets=[{"host": 0, "uri": "ccnx:/test/ignored"}],
            auto={"publishers": [2], "uri_prefix": "ccnx:/test"},
        ),
        run_dir=tmp_path,
    )
    assert scenario.publisher_ids == set()
    assert scenario.uri_publishers == {}
