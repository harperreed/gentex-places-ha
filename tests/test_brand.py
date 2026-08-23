# Copyright (c) 2026 Harper Reed
# ABOUTME: Verifies the original Home Shield source, provenance, and PNG exports.
# ABOUTME: Keeps Home Assistant and HACS brand assets licensed and dimensionally exact.
"""Brand asset contract tests."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

_ROOT = Path(__file__).parents[1]
_BRAND = _ROOT / "custom_components/gentex_place/brand"
_OPAQUE_ALPHA = 255


@pytest.mark.parametrize(
    ("name", "size"),
    [("icon.png", (256, 256)), ("icon@2x.png", (512, 512))],
)
def test_brand_png_contract(name: str, size: tuple[int, int]) -> None:
    with Image.open(_BRAND / name) as icon:
        assert icon.format == "PNG"
        assert icon.size == size
        assert icon.mode == "RGBA"
        alpha = icon.getchannel("A")
        assert alpha.getextrema()[0] == 0
        assert alpha.getextrema()[1] == _OPAQUE_ALPHA


def test_brand_source_and_provenance_are_project_owned() -> None:
    source = (_ROOT / "docs/brand/home-shield.svg").read_text()
    provenance = (_ROOT / "docs/brand-provenance.md").read_text()
    assert "<svg" in source
    assert "Home Shield" in source
    assert "August 23, 2026" in provenance
    assert "does not incorporate third-party artwork" in provenance
    assert "MIT License" in provenance


def test_copyright_belongs_to_harper_reed() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 - repository-local Git query
        cwd=_ROOT,
        check=True,
        capture_output=True,
        shell=False,
    ).stdout.split(b"\0")
    forbidden = b"Copyright (c) 2026 " + b"Gentex"

    assert (_ROOT / "LICENSE").read_text().splitlines()[0] == (
        "Copyright (c) 2026 Harper Reed"
    )
    assert (
        "`Copyright (c) 2026 Harper Reed`"
        in (_ROOT / "docs/brand-provenance.md").read_text()
    )
    assert all(
        forbidden not in (_ROOT / relative.decode()).read_bytes()
        for relative in tracked
        if relative
    )
