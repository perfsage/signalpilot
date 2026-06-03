from signalpilot.deepdive import DeepDiveOrchestrator
from signalpilot.models import SignalKind


class TestParseTcpdump:
    def test_tcp_resets_detected(self):
        output = (
            "12:00:01.123 IP 10.0.0.1.8080 > 10.0.0.2.52341: Flags [R.], seq 0, ack 1\n"
            "12:00:01.124 IP 10.0.0.1.8080 > 10.0.0.3.52342: Flags [R], seq 0"
        )
        sigs = DeepDiveOrchestrator.parse_tcpdump_text(output)
        reset_sigs = [s for s in sigs if s.kind == SignalKind.TCP_RETRANSMIT]
        assert len(reset_sigs) > 0
        assert any(s.value == 2.0 for s in reset_sigs)  # 2 resets

    def test_no_anomalies_empty_signals(self):
        output = "12:00:01 IP 10.0.0.1 > 10.0.0.2: Flags [S], seq 12345"
        sigs = DeepDiveOrchestrator.parse_tcpdump_text(output)
        assert sigs == []

    def test_empty_input(self):
        assert DeepDiveOrchestrator.parse_tcpdump_text("") == []

    def test_retransmit_keyword_detected(self):
        output = "12:00:01 IP 10.0.0.1 > 10.0.0.2: TCP retransmit detected"
        sigs = DeepDiveOrchestrator.parse_tcpdump_text(output)
        retransmit_sigs = [s for s in sigs if s.kind == SignalKind.TCP_RETRANSMIT]
        assert len(retransmit_sigs) > 0

    def test_high_severity_above_ten_resets(self):
        lines = "\n".join(
            f"12:00:01 IP 10.0.0.1 > 10.0.0.2: Flags [R], seq {i}"
            for i in range(11)
        )
        sigs = DeepDiveOrchestrator.parse_tcpdump_text(lines)
        reset_sigs = [s for s in sigs if "resets" in s.message]
        assert len(reset_sigs) == 1
        assert reset_sigs[0].severity.value == "high"
