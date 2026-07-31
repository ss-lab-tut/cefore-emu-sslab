"""Contract tests for the Verdict module (src/core/verdict.py).

Pins the per-op success criteria, the tri-state Factor semantics, and the
pub/sub invariant (timed_out/cancelled + non-empty artifact = success).
"""

from src.core.verdict import (
    COMPLETED_MARKER,
    PUB_DELIVERED_MARKER,
    CcninfoVerdict,
    Verdict,
    ccninfo_failure_reasons,
    failure_reasons,
    from_log,
    from_record,
    from_runtime_ccninfo,
    from_runtime_get,
    from_runtime_pub,
    from_runtime_put,
    from_runtime_sub,
)

GET_OK_LOG = f"[cefgetfile] URI = ccnx:/test/a\n{COMPLETED_MARKER}\n"
GET_PARTIAL_LOG = "[cefgetfile] URI = ccnx:/test/a\n[cefgetfile] Duration = 1.0 sec\n"
GET_FAIL_LOG = "[cefgetfile] Could not receive anything\n"


class TestFromRuntimeGet:
    def test_success_requires_all_three_factors(self):
        v = from_runtime_get(0, GET_OK_LOG, output_nonempty=True)
        assert v.success is True
        assert v.has_completed_log is True
        assert v.has_output_file is True

    def test_nonzero_exit_fails(self):
        v = from_runtime_get(1, GET_OK_LOG, output_nonempty=True)
        assert v.success is False
        assert v.has_completed_log is True

    def test_missing_marker_fails(self):
        v = from_runtime_get(0, GET_PARTIAL_LOG, output_nonempty=True)
        assert v.success is False
        assert v.has_completed_log is False

    def test_missing_output_fails(self):
        v = from_runtime_get(0, GET_OK_LOG, output_nonempty=False)
        assert v.success is False
        assert v.has_output_file is False


class TestFromRuntimePut:
    def test_exit_zero_succeeds(self):
        v = from_runtime_put(0)
        assert v.success is True
        assert v.has_completed_log is None
        assert v.has_output_file is None

    def test_nonzero_exit_fails(self):
        assert from_runtime_put(1).success is False


class TestFromRuntimeSub:
    """Pins the pub/sub invariant from result_detect."""

    def test_clean_exit_with_artifact(self):
        v = from_runtime_sub(0, False, False, True, artifact_path="x/RNP0x1.out")
        assert v.success is True
        assert v.artifact_path == "x/RNP0x1.out"

    def test_timed_out_with_artifact_is_success(self):
        assert from_runtime_sub(-15, True, False, True).success is True

    def test_cancelled_with_artifact_is_success(self):
        assert from_runtime_sub(-9, False, True, True).success is True

    def test_artifact_missing_fails_even_on_clean_exit(self):
        v = from_runtime_sub(0, False, False, False)
        assert v.success is False
        assert v.has_output_file is False

    def test_nonzero_exit_without_deadline_fails(self):
        assert from_runtime_sub(1, False, False, True).success is False

    def test_marker_factor_not_applicable(self):
        assert from_runtime_sub(0, False, False, True).has_completed_log is None


class TestFromRuntimePub:
    def test_exit_zero_not_timed_out(self):
        v = from_runtime_pub(0, False)
        assert v.success is True
        assert v.has_completed_log is None
        assert v.has_output_file is None

    def test_timed_out_fails(self):
        assert from_runtime_pub(0, True).success is False

    def test_nonzero_exit_fails(self):
        assert from_runtime_pub(2, False).success is False


class TestFromLog:
    """Definitive-factor rule: exit code / artifacts are unknown here."""

    def test_get_marker_decides_true(self):
        v = from_log("cefgetfile", GET_OK_LOG)
        assert v.success is True
        assert v.has_completed_log is True
        assert v.has_output_file is None
        assert v.exit_code is None

    def test_get_without_marker_is_false(self):
        assert from_log("cefgetfile", GET_PARTIAL_LOG).success is False

    def test_failure_pattern_wins(self):
        assert from_log("cefgetfile", GET_FAIL_LOG).success is False

    def test_empty_log_is_false_for_all_ops(self):
        for cmd in ("cefputfile", "cefgetfile", "cefpubfile", "cefsubfile"):
            assert from_log(cmd, "  \n").success is False

    def test_put_fields_present_decides(self):
        text = "[cefputfile] URI = ccnx:/test/a\n"
        assert from_log("cefputfile", text, fields_present=True).success is True
        assert from_log("cefputfile", text, fields_present=False).success is False

    def test_sub_stays_unknown(self):
        # sub has no in-log definitive Factor at all, marker or otherwise.
        assert from_log("cefsubfile", "[cefsubfile] URI = ccnx:/a\n").success is None

    def test_pub_without_delivery_marker_stays_unknown(self):
        # Deliberately updated 2026-07-07: fields alone (no delivery marker)
        # are not definitive for pub, unlike put's fields_present rule.
        assert from_log("cefpubfile", "[cefpubfile] URI = ccnx:/a\n").success is None

    def test_pub_with_delivery_marker_decides_true(self):
        text = f"[cefpubfile] URI = ccnx:/a\n[cefpubfile] {PUB_DELIVERED_MARKER}\n"
        assert from_log("cefpubfile", text).success is True

    def test_marker_factor_only_applies_to_get(self):
        assert from_log("cefputfile", "x", fields_present=True).has_completed_log is None


class TestFromRecord:
    def test_stored_factors_are_authoritative(self):
        v = from_record(
            {
                "op_type": "sub",
                "success": True,
                "has_completed_log": None,
                "has_output_file": True,
                "exit_code": -15,
            }
        )
        assert v.success is True
        assert v.has_completed_log is None
        assert v.has_output_file is True
        assert v.exit_code == -15

    def test_missing_op_type_is_legacy_get(self):
        assert from_record({"success": True}).op_type == "get"

    def test_non_bool_values_are_unknown(self):
        v = from_record({"success": "yes", "has_completed_log": 1})
        assert v.success is None
        assert v.has_completed_log is None


class TestFailureReasons:
    def test_none_factors_never_count(self):
        v = Verdict("pub", False, None, None, exit_code=1)
        reasons = failure_reasons(v)
        assert reasons == {
            "exit_code_nonzero": True,
            "missing_completed_log": False,
            "missing_output_file": False,
        }

    def test_known_false_factors_count(self):
        v = Verdict("get", False, False, False, exit_code=0)
        reasons = failure_reasons(v)
        assert reasons == {
            "exit_code_nonzero": False,
            "missing_completed_log": True,
            "missing_output_file": True,
        }

    def test_unknown_exit_code_not_counted(self):
        assert failure_reasons(Verdict("get", None, None, None))["exit_code_nonzero"] is False


class TestFromRuntimeCcninfo:
    """Pins the ccninfo success formula and the tri-state match Factors.

    No expectations supplied (expected_responder/expected_route both None) is
    the baseline "just confirm a reply arrived" case; the two expectation
    args layer additional known-good/known-bad conditions on top.
    """

    def test_clean_reply_no_expectations_succeeds(self):
        v = from_runtime_ccninfo(0, False, False, True, "h3", ("h1", "h2", "h3"), None, None)
        assert v.success is True
        assert v.responder_matched is None
        assert v.route_matched is None

    def test_nonzero_exit_fails(self):
        v = from_runtime_ccninfo(1, False, False, True, "h3", (), None, None)
        assert v.success is False

    def test_timed_out_fails_even_on_exit_zero(self):
        # cefinfo can be force-killed by the outer deadline after its own
        # process already returned 0 (e.g. wait() races the timeout) — ccninfo
        # has no sub-style "delivered before the kill" carve-out, so
        # timed_out alone is disqualifying regardless of exit_code.
        v = from_runtime_ccninfo(0, timed_out=True, cancelled=False, reply_received=True,
                                  responder="h3", route_nodes=(), expected_responder=None,
                                  expected_route=None)
        assert v.success is False
        assert v.timed_out is True

    def test_cancelled_fails_even_on_exit_zero(self):
        v = from_runtime_ccninfo(0, timed_out=False, cancelled=True, reply_received=True,
                                  responder="h3", route_nodes=(), expected_responder=None,
                                  expected_route=None)
        assert v.success is False
        assert v.cancelled is True

    def test_no_reply_fails(self):
        v = from_runtime_ccninfo(0, False, False, False, None, (), None, None)
        assert v.success is False
        assert v.reply_received is False

    def test_unset_expectations_never_cause_failure(self):
        # Both match Factors are None (not-applicable) here; success must be
        # decided purely by exit_code/timed_out/cancelled/reply_received.
        v = from_runtime_ccninfo(0, False, False, True, "anything", ("x", "y"), None, None)
        assert v.responder_matched is None
        assert v.route_matched is None
        assert v.success is True

    def test_responder_exact_match_succeeds(self):
        v = from_runtime_ccninfo(0, False, False, True, "h3", (), "h3", None)
        assert v.responder_matched is True
        assert v.success is True

    def test_responder_substring_no_longer_matches(self):
        # 2026-07-27 external review regression: "h3" inside "host-h3-x"
        # used to substring-match; exact equality now correctly rejects it.
        v = from_runtime_ccninfo(0, False, False, True, "host-h3-x", (), "h3", None)
        assert v.responder_matched is False
        assert v.success is False

    def test_responder_prefix_false_green_h1_vs_h10(self):
        # 2026-07-27 external review regression: "h1" as expected must NOT
        # match responder "h10" (the substring bug this fix closes).
        v = from_runtime_ccninfo(0, False, False, True, "h10", (), "h1", None)
        assert v.responder_matched is False
        assert v.success is False

    def test_responder_mismatch_fails(self):
        v = from_runtime_ccninfo(0, False, False, True, "h5", (), "h3", None)
        assert v.responder_matched is False
        assert v.success is False

    def test_responder_expected_but_none_observed_is_false_not_none(self):
        # Spec: an expectation set against a missing responder is a known
        # mismatch (False), not an open question (None).
        v = from_runtime_ccninfo(0, False, False, True, None, (), "h3", None)
        assert v.responder_matched is False
        assert v.success is False

    def test_route_in_order_with_gaps_matches(self):
        # Re-tokenized for exact-match: observed has extra hops between
        # the expected ones (gaps allowed).
        v = from_runtime_ccninfo(0, False, False, True, None, ("a", "z", "b"), None, ("a", "b"))
        assert v.route_matched is True
        assert v.success is True

    def test_route_out_of_order_fails(self):
        v = from_runtime_ccninfo(0, False, False, True, None, ("b", "a"), None, ("a", "b"))
        assert v.route_matched is False
        assert v.success is False

    def test_route_middle_gap_matches(self):
        # Gap tests elsewhere only leave a trailing gap (unmatched tail hops),
        # which a scan that forgets to advance `pos` after a match would also
        # pass. This one has the gap *between* two matched tokens, which only
        # passes if each token consumes a distinct, forward-only hop.
        v = from_runtime_ccninfo(
            0, False, False, True, None, ("a", "z", "b"), None, ("a", "b")
        )
        assert v.route_matched is True

    def test_route_tokens_must_consume_distinct_hops(self):
        # Both expected tokens name the same node "a" — this must fail,
        # because "subsequence" means each token claims its own hop
        # position; a scan that never advances `pos` past a matched hop
        # would wrongly accept two "a" tokens satisfied by one "a" hop.
        v = from_runtime_ccninfo(0, False, False, True, None, ("a",), None, ("a", "a"))
        assert v.route_matched is False
        assert v.success is False

    def test_route_expected_longer_than_observed_fails(self):
        v = from_runtime_ccninfo(0, False, False, True, None, ("a", "b"), None, ("a", "b", "c"))
        assert v.route_matched is False
        assert v.success is False

    def test_route_substring_no_longer_matches(self):
        # 2026-07-27 external review regression: expected "h1" must NOT
        # match observed hop "h10" (the substring bug this fix closes).
        v = from_runtime_ccninfo(0, False, False, True, None, ("h10",), None, ("h1",))
        assert v.route_matched is False
        assert v.success is False

    def test_route_empty_expected_is_trivially_matched(self):
        # Validator upstream rejects an empty expected_route before it ever
        # reaches judgment code; this pins from_runtime_ccninfo's own total
        # behavior for that input, not a claim that callers should send it.
        v = from_runtime_ccninfo(0, False, False, True, None, ("h1", "h2"), None, ())
        assert v.route_matched is True
        assert v.success is True

    def test_both_expectations_hold_together(self):
        v = from_runtime_ccninfo(
            0, False, False, True, "h3", ("a", "b", "h3"), "h3", ("a", "b")
        )
        assert v.responder_matched is True
        assert v.route_matched is True
        assert v.success is True

    def test_route_mismatch_alone_fails_despite_responder_match(self):
        v = from_runtime_ccninfo(0, False, False, True, "h3", ("b", "a"), "h3", ("a", "b"))
        assert v.responder_matched is True
        assert v.route_matched is False
        assert v.success is False


class TestCcninfoFailureReasons:
    def test_none_match_factors_omitted(self):
        v = CcninfoVerdict(
            success=True,
            reply_received=True,
            responder_matched=None,
            route_matched=None,
            exit_code=0,
            timed_out=False,
            cancelled=False,
            responder="h3",
            route_nodes=("h1", "h3"),
        )
        assert ccninfo_failure_reasons(v) == {}

    def test_only_actually_bad_keys_present(self):
        v = CcninfoVerdict(
            success=False,
            reply_received=True,
            responder_matched=False,
            route_matched=None,
            exit_code=1,
            timed_out=False,
            cancelled=False,
            responder="h5",
            route_nodes=(),
        )
        assert ccninfo_failure_reasons(v) == {
            "exit_code_nonzero": True,
            "responder_mismatch": True,
        }

    def test_all_bad_factors_reported(self):
        v = CcninfoVerdict(
            success=False,
            reply_received=False,
            responder_matched=False,
            route_matched=False,
            exit_code=1,
            timed_out=True,
            cancelled=True,
            responder=None,
            route_nodes=(),
        )
        assert ccninfo_failure_reasons(v) == {
            "exit_code_nonzero": True,
            "timed_out": True,
            "cancelled": True,
            "no_reply": True,
            "responder_mismatch": True,
            "route_mismatch": True,
        }
