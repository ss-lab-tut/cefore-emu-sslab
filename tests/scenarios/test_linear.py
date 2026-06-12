"""Behavior tests for the linear scenario FIB programming."""

from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.scenarios.linear import LinearScenario


class TestSetFib:
    def test_routes_every_non_publisher_toward_the_publisher(self):
        scenario = LinearScenario(3)
        fake = FakeCommandRunner()
        scenario._set_fib(None, runner=fake)
        assert [run["node"] for run in fake.runs] == ["h0", "h1"]
        for idx, run in enumerate(fake.runs):
            assert run["argv"] == [
                "cefroute", "add", "ccnx:/test", "udp",
                str(scenario.scheme.host_ip(idx, idx + 1)),
                "-d", f"./h{idx}",
            ]

    def test_failed_add_does_not_abort_remaining_hosts(self):
        scenario = LinearScenario(3)
        fake = FakeCommandRunner()
        fake.on_run = lambda node, argv: (
            CommandResult(returncode=1) if node == "h0" else None
        )
        scenario._set_fib(None, runner=fake)
        assert [run["node"] for run in fake.runs] == ["h0", "h1"]
