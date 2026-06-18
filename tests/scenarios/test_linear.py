"""Behavior tests for the linear scenario FIB programming."""

from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.scenarios.linear import LinearScenario


class TestSetIpAddr:
    def test_assigns_each_interface_with_explicit_slash24_netmask(self):
        """Every ifconfig must carry netmask 255.255.255.0.

        Without it ifconfig applies the classful default (/8 for 10.x), which
        collapses interfaces onto one flat network and breaks routing.
        """
        scenario = LinearScenario(3)
        fake = FakeCommandRunner()
        scenario._set_ip_addr(None, runner=fake)
        s = scenario.scheme
        assert [run["node"] for run in fake.runs] == ["h0", "h1", "h1", "h2"]
        assert [run["argv"] for run in fake.runs] == [
            ["ifconfig", "h0-eth0", str(s.host_ip(0, 0)), "netmask", "255.255.255.0"],
            ["ifconfig", "h1-eth0", str(s.host_ip(0, 1)), "netmask", "255.255.255.0"],
            ["ifconfig", "h1-eth1", str(s.host_ip(1, 1)), "netmask", "255.255.255.0"],
            ["ifconfig", "h2-eth0", str(s.host_ip(1, 2)), "netmask", "255.255.255.0"],
        ]


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
