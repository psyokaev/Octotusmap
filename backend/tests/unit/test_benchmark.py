import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from benchmark import summarize  # noqa: E402


def test_summarize_percentiles():
    s = summarize([float(i) for i in range(1, 101)], errors=2, elapsed_s=2)
    assert (s["p50_ms"], s["p95_ms"], s["max_ms"], s["count"], s["errors"]) == (50.0, 95.0, 100.0, 102, 2)
    assert s["throughput_rps"] == 51.0


def test_summarize_empty():
    s = summarize([], errors=0)
    assert s["count"] == 0 and s["p50_ms"] is None and s["max_ms"] is None
