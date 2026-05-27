from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

BackendName = Literal["auto", "numpy", "numexpr"]


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
