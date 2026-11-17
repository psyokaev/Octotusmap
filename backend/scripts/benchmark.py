"""Đo hiệu năng gần thời gian thực: tải hỗn hợp GET theo mức đồng thời + thời gian một chu kỳ pipeline.

    python scripts/benchmark.py --base http://127.0.0.1:8001 --requests 200 --concurrency 1,10,50 --cycles 3
Tài khoản: --username/--password hoặc ADMIN_USERNAME/ADMIN_PASSWORD trong backend/.env (không in mật khẩu).
Chạy với MỘT server khởi động bằng SCHEDULER_ENABLED=false. --cycles chạy chu kỳ pipeline thật và có tác dụng phụ
(Open-Meteo, snapshot, có thể sinh cảnh báo); dùng --cycles 0 để tránh.
Không đo chỉ đường/tìm kiếm vì gọi dịch vụ ngoài và có giới hạn tần suất.
"""

import argparse
import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = "/api/v1"
# (đường dẫn, trọng số); /health nằm ngoài /api/v1
MIX = [(f"{API}/gis/risk-layers?horizon=0", 5), (f"{API}/gis/features", 3), (f"{API}/forecasts/latest", 4),
       (f"{API}/alerts", 3), (f"{API}/gis/identify?lat=10.74&lon=106.72", 3), (f"{API}/statistics/overview", 2),
       ("/health", 1)]


def summarize(latencies_ms: list[float], errors: int = 0, elapsed_s: float | None = None) -> dict:
    """count/errors/p50/p95/max (ms); percentile kiểu nearest-rank; rỗng -> None."""
    xs = sorted(latencies_ms)

    def pct(p):
        return round(xs[max(0, math.ceil(p / 100 * len(xs)) - 1)], 1) if xs else None

    out = {"count": len(xs) + errors, "errors": errors, "p50_ms": pct(50), "p95_ms": pct(95),
           "max_ms": round(xs[-1], 1) if xs else None}
    if elapsed_s:
        out["throughput_rps"] = round((len(xs) + errors) / elapsed_s, 1)
    return out


def _env(key: str) -> str | None:
    f = Path(__file__).resolve().parents[1] / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def run_level(base: str, headers: dict, n: int, workers: int) -> dict:
    paths = random.choices([p for p, _ in MIX], weights=[w for _, w in MIX], k=n)
    with httpx.Client(base_url=base, headers=headers, timeout=60,
                      limits=httpx.Limits(max_connections=workers)) as c:
        def one(path):
            t = time.perf_counter()
            try:
                ok = c.get(path).status_code < 400
            except httpx.HTTPError:
                ok = False
            return path, (time.perf_counter() - t) * 1000, ok

        t0 = time.perf_counter()
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(one, paths))
        elapsed = time.perf_counter() - t0
    by = {p: ([ms for q, ms, ok in res if q == p and ok], sum(1 for q, _, ok in res if q == p and not ok))
          for p, _ in MIX}
    return {"overall": summarize([ms for _, ms, ok in res if ok], sum(1 for *_, ok in res if not ok), elapsed),
            "endpoints": {p: summarize(*v) for p, v in by.items() if v[0] or v[1]}}


def run_cycles(base: str, headers: dict, k: int) -> list[dict]:
    out = []
    for _ in range(k):
        t = time.perf_counter()
        r = httpx.post(f"{base}{API}/admin/jobs/run-cycle", headers=headers, timeout=600)
        body = r.json() if r.status_code == 200 else {}
        busy = body.get("status") == "BUSY"  # chu kỳ khác đang chạy: không đo được
        out.append({"status": r.status_code, "wall_s": round(time.perf_counter() - t, 2),
                    "seconds": None if busy else body.get("seconds"), "error": busy or r.status_code != 200})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--concurrency", default="1,10,50")
    ap.add_argument("--cycles", type=int, default=3)
    a = ap.parse_args()
    user = a.username or _env("ADMIN_USERNAME") or "admin"
    pw = a.password or _env("ADMIN_PASSWORD")
    if not pw:
        raise SystemExit("Thiếu mật khẩu: dùng --password hoặc ADMIN_PASSWORD trong backend/.env")
    r = httpx.post(f"{a.base}{API}/auth/login", json={"username": user, "password": pw}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Đăng nhập thất bại: HTTP {r.status_code}")  # đăng nhập giới hạn 10 lần/phút: chỉ một lần
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    report = {"base": a.base, "requests": a.requests, "levels": {}, "cycles": []}
    for w in (int(x) for x in a.concurrency.split(",")):
        report["levels"][str(w)] = run_level(a.base, headers, a.requests, w)
    if a.cycles > 0:
        report["cycles"] = run_cycles(a.base, headers, a.cycles)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{'concurrency':>11} {'count':>6} {'err':>4} {'p50':>8} {'p95':>8} {'max':>8} {'req/s':>7}")
    for w, lv in report["levels"].items():
        o = lv["overall"]
        print(f"{w:>11} {o['count']:>6} {o['errors']:>4} {o['p50_ms']!s:>8} {o['p95_ms']!s:>8} "
              f"{o['max_ms']!s:>8} {o['throughput_rps']!s:>7}")
    for i, c in enumerate(report["cycles"], 1):
        print(f"cycle {i}: {c['wall_s']} s (server seconds={c['seconds']}, HTTP {c['status']}{', LỖI' if c['error'] else ''})")


if __name__ == "__main__":
    main()
