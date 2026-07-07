"""Contract tests for the Verdict module (src/core/verdict.py).

Pins the per-op success criteria, the tri-state Factor semantics, and the
pub/sub invariant (timed_out/cancelled + non-empty artifact = success).
"""

from src.core.verdict import (
    COMPLETED_MARKER,
    Verdict,
    failure_reasons,
    from_log,
    from_record,
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

    def test_sub_and_pub_stay_unknown(self):
        assert from_log("cefsubfile", "[cefsubfile] URI = ccnx:/a\n").success is None
        assert from_log("cefpubfile", "[cefpubfile] URI = ccnx:/a\n").success is None

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
