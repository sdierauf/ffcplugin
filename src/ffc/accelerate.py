from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Literal

import numpy as np

BackendName = Literal["auto", "numpy", "numexpr", "mlx"]


@dataclass(frozen=True)
class Backend:
    name: str
    detail: str


def choose_backend(requested: BackendName, numexpr_threads: int | None = None) -> Backend:
    if requested == "numpy":
        return Backend("numpy", "NumPy vectorized CPU")

    if requested == "numexpr":
        _configure_numexpr(numexpr_threads)
        return Backend("numexpr", "NumExpr multi-threaded native CPU")

    if requested == "mlx":
        _require_mlx()
        return Backend("mlx", "MLX Apple Silicon/Metal")

    if _can_import_numexpr():
        _configure_numexpr(numexpr_threads)
        return Backend("numexpr", "NumExpr multi-threaded native CPU")

    return Backend("numpy", "NumPy vectorized CPU")


def correct_plane(
    scan_plane: np.ndarray,
    gain_plane: np.ndarray,
    *,
    black: float,
    white: float,
    backend: Backend,
) -> np.ndarray:
    if backend.name == "numexpr":
        import numexpr as ne

        corrected = ne.evaluate(
            "((scan - black) * gain) + black",
            local_dict={
                "scan": scan_plane,
                "gain": gain_plane,
                "black": float(black),
                "white": float(white),
            },
        )
        clipped = ne.evaluate(
            "where(corrected < 0, 0, where(corrected > white, white, corrected))",
            local_dict={"corrected": corrected, "white": float(white)},
        )
        return np.rint(clipped).astype(np.uint16, copy=False)

    if backend.name == "mlx":
        import mlx.core as mx

        scan_mx = mx.array(scan_plane.astype(np.float32, copy=False))
        gain_mx = mx.array(gain_plane.astype(np.float32, copy=False))
        corrected = ((scan_mx - black) * gain_mx) + black
        corrected = mx.clip(corrected, 0.0, white)
        mx.eval(corrected)
        return np.rint(np.array(corrected)).astype(np.uint16, copy=False)

    corrected = ((scan_plane.astype(np.float32, copy=False) - black) * gain_plane) + black
    np.clip(corrected, 0.0, white, out=corrected)
    return np.rint(corrected).astype(np.uint16, copy=False)


def _configure_numexpr(threads: int | None) -> None:
    import numexpr as ne

    if threads is not None and threads > 0:
        ne.set_num_threads(threads)


def _can_import_numexpr() -> bool:
    try:
        import numexpr  # noqa: F401
    except Exception:
        return False
    return True


def _require_mlx() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("The MLX backend is only supported on Apple Silicon Macs.")
    try:
        import mlx.core  # noqa: F401
    except Exception as exc:
        raise RuntimeError("The MLX backend requires installing the optional 'apple' extra.") from exc
