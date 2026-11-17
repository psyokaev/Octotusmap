"""Kiến trúc mạng hồi quy LSTM/GRU đa đầu ra (Keras 3 / TensorFlow)."""

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import keras  # noqa: E402
from keras import layers  # noqa: E402

from app.ai.forecasting.preprocessing import FEATURES, HORIZON, LOOKBACK  # noqa: E402


def build_model(cell: str = "lstm", units: int = 48, dropout: float = 0.1,
                heads: tuple[str, ...] = ("rain", "wl", "flood")) -> keras.Model:
    """Encoder RNN -> các đầu ra 6 bước: mưa (log1p mm), mực nước tương đối (chuẩn hoá), xác suất ngập.
    Dữ liệu thật chưa có nhãn ngập -> chỉ dùng heads=("rain",)."""
    rnn = {"lstm": layers.LSTM, "gru": layers.GRU}[cell]
    inp = keras.Input(shape=(LOOKBACK, len(FEATURES)), name="history")
    x = rnn(units, return_sequences=True, dropout=dropout)(inp)
    x = rnn(units // 2, dropout=dropout)(x)
    x = layers.Dense(64, activation="relu")(x)
    spec = {"rain": ("softplus", "mse", 1.0), "wl": (None, "mse", 1.0), "flood": ("sigmoid", "binary_crossentropy", 2.0)}
    outs = [layers.Dense(HORIZON, activation=spec[h][0], name=h)(x) for h in heads]
    model = keras.Model(inp, outs, name=f"flood_{cell}")
    model.compile(optimizer=keras.optimizers.Adam(1e-3), loss={h: spec[h][1] for h in heads},
                  loss_weights={h: spec[h][2] for h in heads})
    return model
