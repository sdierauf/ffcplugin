from __future__ import annotations

from types import SimpleNamespace

from ffc.rawio import _crop


def test_crop_preserves_explicit_zero_crop_margin() -> None:
    raw = SimpleNamespace(
        sizes=SimpleNamespace(
            crop_width=80,
            crop_height=60,
            width=80,
            height=60,
            crop_left_margin=0,
            crop_top_margin=0,
            left_margin=12,
            top_margin=8,
        ),
        raw_image_visible=_visible(60, 80),
    )

    assert _crop(raw, (64, 100)) == ((0, 0), (80, 60))


def test_crop_uses_visible_margins_when_crop_box_is_missing() -> None:
    raw = SimpleNamespace(
        sizes=SimpleNamespace(
            crop_width=0,
            crop_height=0,
            width=80,
            height=60,
            crop_left_margin=0,
            crop_top_margin=0,
            left_margin=12,
            top_margin=8,
        ),
        raw_image_visible=_visible(60, 80),
    )

    assert _crop(raw, (70, 100)) == ((12, 8), (80, 60))


def test_crop_clamps_to_raw_bounds() -> None:
    raw = SimpleNamespace(
        sizes=SimpleNamespace(
            crop_width=120,
            crop_height=90,
            width=120,
            height=90,
            crop_left_margin=80,
            crop_top_margin=50,
            left_margin=0,
            top_margin=0,
        ),
        raw_image_visible=_visible(90, 120),
    )

    assert _crop(raw, (60, 100)) == ((80, 50), (20, 10))


def _visible(height: int, width: int) -> object:
    return SimpleNamespace(shape=(height, width))
