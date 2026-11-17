"""Đánh giá Accuracy/F1 của quy tắc rủi ro (chỉ đọc DB). Chạy: python scripts\\evaluate_risk.py"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.evaluation.risk_eval import evaluate, load_inputs  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        res = evaluate(**load_inputs(db))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\n{res['note']}\nSự kiện bỏ qua vì thiếu quận: {res['skipped_null_area_events']}\n")
    print(f"{'nhóm':<42}{'n':>7}{'dương':>7}{'acc':>7}{'P':>7}{'R':>7}{'F1':>7}  tp/fp/fn/tn")
    for k, v in res.items():
        if isinstance(v, dict):
            print(f"{k:<42}{v['n']:>7}{v['positives']:>7}{v['accuracy']:>7.3f}{v['precision']:>7.3f}"
                  f"{v['recall']:>7.3f}{v['f1']:>7.3f}  {v['tp']}/{v['fp']}/{v['fn']}/{v['tn']}")


if __name__ == "__main__":
    main()
