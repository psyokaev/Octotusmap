"""Sao chép toàn bộ dữ liệu từ MySQL (MYSQL_* trong .env, chỉ đọc) sang PostgreSQL/PostGIS (POSTGRES_*).

Chạy từ thư mục backend, sau khi đã `alembic upgrade head` trên PostgreSQL:
    .venv\\Scripts\\python scripts\\migrate_mysql_to_postgres.py [--truncate] [--batch 5000]

- Từ chối chạy nếu bảng đích đã có dữ liệu, trừ khi có --truncate (xoá sạch bảng đích rồi nạp lại).
- Đọc MySQL bằng con trỏ server-side (không nạp hết vào bộ nhớ), ghi theo lô; hình học đi qua WKT (lon lat).
- Kiểm tra MySQL (SELECT 1) trước; truncate + nạp + đặt lại sequence + đối chiếu số dòng trong MỘT transaction PostgreSQL:
  lỗi hoặc lệch -> rollback, thoát mã 1.
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _mysql_conn():
    import pymysql  # chỉ script này cần PyMySQL
    from dotenv import dotenv_values

    env = dotenv_values(BACKEND / ".env")
    c = pymysql.connect(host=env.get("MYSQL_HOST") or "127.0.0.1", port=int(env.get("MYSQL_PORT") or 3306),
                        user=env.get("MYSQL_USER") or "root", password=env.get("MYSQL_PASSWORD") or "",
                        database=env.get("MYSQL_DATABASE") or "urban_flood_dss", charset="utf8mb4",
                        cursorclass=pymysql.cursors.SSCursor)
    with c.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return c


def _convert(table, rows: list[tuple], cols: list[str]) -> list[dict]:
    from sqlalchemy import JSON, Boolean

    fix = {}
    for c in cols:
        t = table.c[c].type
        if isinstance(t, Boolean):
            fix[c] = lambda v: None if v is None else bool(v)
        elif isinstance(t, JSON):  # PyMySQL trả JSON dạng chuỗi
            fix[c] = lambda v: json.loads(v) if isinstance(v, (str, bytes)) else v
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        for c, f in fix.items():
            d[c] = f(d[c])
        out.append(d)
    return out


def _self_fk_sorted(table, rows: list[dict]) -> list[dict]:
    """Bảng tự tham chiếu (administrative_areas.parent_id): cha phải vào trước con."""
    col = next(fk.parent.name for fk in table.foreign_keys if fk.column.table is table)
    pk = next(iter(table.primary_key.columns)).name
    done, out, pending = set(), [], rows
    while pending:
        ready = [r for r in pending if r[col] is None or r[col] in done]
        if not ready:
            raise SystemExit(f"{table.name}: vòng tham chiếu trong {col}")
        out += ready
        done |= {r[pk] for r in ready}
        pending = [r for r in pending if r not in ready]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truncate", action="store_true", help="xoá sạch bảng đích trước khi nạp")
    ap.add_argument("--batch", type=int, default=5000)
    a = ap.parse_args()

    from sqlalchemy import func, select, text

    import app.models  # noqa: F401
    from app.core.database import Base, engine
    from app.core.spatial import Geometry

    tables = Base.metadata.sorted_tables  # thứ tự an toàn theo khoá ngoại
    my = _mysql_conn()
    with my.cursor() as cur:  # kiểm tra MySQL trước khi động tới PostgreSQL
        cur.execute("SELECT 1")
    # Một transaction PostgreSQL cho truncate + nạp + kiểm tra: lỗi hoặc lệch số dòng -> rollback, đích còn nguyên.
    with engine.begin() as pg:
        nonempty = [t.name for t in tables if pg.execute(select(func.count()).select_from(t)).scalar()]
        if nonempty and not a.truncate:
            sys.exit(f"Bảng đích không rỗng ({', '.join(nonempty)}). Thêm --truncate để xoá và nạp lại.")
        if nonempty:
            pg.execute(text("TRUNCATE " + ", ".join(f'"{t.name}"' for t in tables) + " RESTART IDENTITY CASCADE"))
        report = []
        for t in tables:
            cols = [c.name for c in t.columns]
            sel = ", ".join(f"ST_AsText(`{c}`, 'axis-order=long-lat')" if isinstance(t.c[c].type, Geometry)
                            else f"`{c}`" for c in cols)
            pk = ", ".join(f"`{c.name}`" for c in t.primary_key.columns)
            self_ref = any(fk.column.table is t for fk in t.foreign_keys)
            n = 0
            with my.cursor() as cur:
                cur.execute(f"SELECT {sel} FROM `{t.name}` ORDER BY {pk}")  # noqa: S608
                while True:
                    rows = cur.fetchmany(10**9 if self_ref else a.batch)
                    if not rows:
                        break
                    data = _convert(t, rows, cols)
                    if self_ref:
                        data = _self_fk_sorted(t, data)
                    for i in range(0, len(data), a.batch):
                        chunk = data[i:i + a.batch]
                        pg.execute(t.insert(), chunk)
                        n += len(chunk)
                        print(f"  {t.name}: {n}", end="\r", flush=True)
            report.append((t, n))
        with my.cursor() as cur:  # đếm nguồn sau cùng (không phụ thuộc số dòng đã đọc)
            src = {}
            for t, _ in report:
                cur.execute(f"SELECT COUNT(*) FROM `{t.name}`")  # noqa: S608
                src[t.name] = cur.fetchone()[0]
        my.close()

        bad = []
        for t, _ in report:
            pkcols = list(t.primary_key.columns)
            if len(pkcols) == 1 and pkcols[0].type.python_type is int:
                name = pkcols[0].name
                pg.execute(text("SELECT setval(pg_get_serial_sequence(:t, :c), COALESCE(MAX(" + f'"{name}"' + "), 1), "  # noqa: S608
                                "MAX(" + f'"{name}"' + ") IS NOT NULL) FROM " + f'"{t.name}"'),
                           {"t": t.name, "c": name})
            dst = pg.execute(select(func.count()).select_from(t)).scalar()
            flag = "" if dst == src[t.name] else "  <-- LỆCH"
            if flag:
                bad.append(t.name)
            print(f"{t.name:28s} MySQL {src[t.name]:>9}  PostgreSQL {dst:>9}{flag}")
        if bad:
            sys.exit(f"Số dòng lệch ở: {', '.join(bad)} (đã rollback, PostgreSQL không đổi)")
    print("Hoàn tất: số dòng khớp ở mọi bảng, sequence đã đặt lại.")


if __name__ == "__main__":
    main()
