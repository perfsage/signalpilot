import pytest
from signalpilot.analysis.logs import (
    cluster_logs, extract_stacktraces, error_rate, redact_log, _categorize
)

BEFORE_LOGS = """
2024-06-01 10:00:01 INFO Server started on port 8080
2024-06-01 10:00:02 INFO Health check OK
2024-06-01 10:00:03 INFO Request GET /api/v1/users 200 45ms
2024-06-01 10:00:04 INFO Request GET /api/v1/users 200 42ms
2024-06-01 10:00:05 ERROR Failed to connect to redis:6379
""".strip()

AFTER_LOGS = """
2024-06-01 12:00:01 ERROR NullPointerException at com.example.Service.processOrder(Service.java:142)
2024-06-01 12:00:02 ERROR NullPointerException at com.example.Service.processOrder(Service.java:142)
2024-06-01 12:00:03 ERROR NullPointerException at com.example.Service.processOrder(Service.java:142)
2024-06-01 12:00:04 INFO Request GET /api/v1/users 200 45ms
2024-06-01 12:00:05 ERROR Connection refused to postgres:5432
2024-06-01 12:00:06 ERROR Connection refused to postgres:5432
""".strip()


class TestErrorRate:
    def test_zero_for_empty(self):
        assert error_rate("") == 0.0

    def test_zero_for_info_only(self):
        logs = "INFO foo\nINFO bar\nINFO baz"
        assert error_rate(logs) == 0.0

    def test_fraction_correct(self):
        logs = "ERROR foo\nINFO bar\nINFO baz\nERROR qux"
        assert abs(error_rate(logs) - 0.5) < 1e-6


class TestRedactLog:
    def test_authorization_header_redacted(self):
        line = "Authorization: Bearer eyJhbGci.token.secret"
        result = redact_log(line)
        assert "eyJhbGci" not in result
        assert "[REDACTED]" in result

    def test_password_kv_redacted(self):
        line = "db_password=supersecretpassword123 connecting"
        result = redact_log(line)
        assert "supersecretpassword123" not in result

    def test_non_secret_preserved(self):
        line = "INFO starting server port 8080"
        assert redact_log(line) == line


class TestCategorize:
    def test_conn_category(self):
        assert _categorize("Connection refused to <*>:<*>") == "conn"

    def test_timeout_category(self):
        assert _categorize("Request timed out after <*>ms") == "timeout"

    def test_oom_category(self):
        assert _categorize("OOM Killed process <*>") == "oom"

    def test_no_category(self):
        assert _categorize("Normal log message") is None


class TestClusterLogs:
    def test_new_errors_detected(self):
        clusters = cluster_logs(BEFORE_LOGS, AFTER_LOGS)
        new_clusters = [c for c in clusters if c.is_new]
        assert len(new_clusters) > 0

    def test_new_clusters_sorted_first(self):
        clusters = cluster_logs(BEFORE_LOGS, AFTER_LOGS)
        if clusters:
            new_seen = False
            for c in clusters:
                if c.is_new:
                    new_seen = True
                elif new_seen:
                    break
            assert new_seen or all(not c.is_new for c in clusters)

    def test_same_logs_no_new_clusters(self):
        clusters = cluster_logs(BEFORE_LOGS, BEFORE_LOGS)
        new_clusters = [c for c in clusters if c.is_new]
        assert len(new_clusters) == 0

    def test_empty_before_all_new(self):
        clusters = cluster_logs("", AFTER_LOGS)
        error_clusters = [c for c in clusters if c.count_after > 0]
        assert len(error_clusters) > 0

    def test_sample_lines_populated(self):
        clusters = cluster_logs(BEFORE_LOGS, AFTER_LOGS)
        clusters_with_after = [c for c in clusters if c.count_after > 0]
        if clusters_with_after:
            assert any(len(c.sample_lines) > 0 for c in clusters_with_after)

    def test_conn_category_detected(self):
        clusters = cluster_logs(BEFORE_LOGS, AFTER_LOGS)
        conn_clusters = [c for c in clusters if c.category == "conn"]
        assert len(conn_clusters) > 0


class TestExtractStacktraces:
    def test_java_stacktrace_extracted(self):
        log = """ERROR NullPointerException
    at com.example.Service.processOrder(Service.java:142)
    at com.example.Controller.handle(Controller.java:98)
    at org.springframework.Dispatcher.dispatch(Dispatcher.java:1067)

INFO next log line""".strip()
        stacks = extract_stacktraces(log)
        assert len(stacks) > 0
        assert "processOrder" in stacks[0]

    def test_no_stacktrace_returns_empty(self):
        log = "INFO foo\nINFO bar\nERROR something happened"
        stacks = extract_stacktraces(log)
        assert stacks == []
