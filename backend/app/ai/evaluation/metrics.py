"""Chỉ số đánh giá: hồi quy (MAE/RMSE) và phân loại xác suất (P/R/F1/Brier/AUC)."""

import numpy as np


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = np.asarray(y_pred, float) - np.asarray(y_true, float)
    per_h = {
        f"h{h + 1}": {"mae": float(np.abs(err[:, h]).mean()), "rmse": float(np.sqrt((err[:, h] ** 2).mean()))}
        for h in range(err.shape[1])
    }
    return {"mae": float(np.abs(err).mean()), "rmse": float(np.sqrt((err ** 2).mean())), "per_horizon": per_h}


def classification_metrics(y_true: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> dict:
    yt = np.asarray(y_true).ravel().astype(int)
    p = np.clip(np.asarray(prob, float).ravel(), 0, 1)
    yp = (p >= threshold).astype(int)
    tp = int(((yp == 1) & (yt == 1)).sum())
    tn = int(((yp == 0) & (yt == 0)).sum())
    fp = int(((yp == 1) & (yt == 0)).sum())
    fn = int(((yp == 0) & (yt == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "accuracy": (tp + tn) / max(len(yt), 1),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "brier": float(((p - yt) ** 2).mean()) if len(yt) else 0.0,
        "roc_auc": roc_auc(yt, p),
        "positive_rate": float(yt.mean()) if len(yt) else 0.0,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "threshold": threshold,
    }


def roc_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    # Mann-Whitney U, xử lý giá trị bằng nhau bằng hạng trung bình
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    vals = np.concatenate([pos, neg])[order]
    ranks = np.empty(len(vals))
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[i]:
            j += 1
        ranks[i:j + 1] = (i + j) / 2 + 1
        i = j + 1
    r = np.empty(len(vals))
    r[order] = ranks
    u = r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2
    return float(u / (len(pos) * len(neg)))


def best_f1_threshold(y_true: np.ndarray, prob: np.ndarray) -> float:
    """Chọn ngưỡng trên tập validation (không dùng tập test)."""
    best, best_t = -1.0, 0.5
    for t in np.linspace(0.05, 0.95, 19):
        f = classification_metrics(y_true, prob, float(t))["f1"]
        if f > best:
            best, best_t = f, float(t)
    return best_t
