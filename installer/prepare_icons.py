"""Generate the placeholder icon set that `desktop/src-tauri/tauri.conf.json`
references.

`tauri.conf.json` declares these icons in `bundle.icon`:
    icons/32x32.png
    icons/128x128.png
    icons/128x128@2x.png
    icons/icon.icns
    icons/icon.ico

A Windows build will fail unless every listed file exists, even files
(.icns) that would only be used when targeting macOS. This script emits a
branded CHERYY placeholder for each so the build can complete and CI can
emit real installers.

Run from repo root:
    python installer\\prepare_icons.py [output_dir]

Or from CI:
    python installer/prepare_icons.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path


def _build_cheryy_icon(size: int) -> "PIL.Image.Image":
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (15, 23, 42, 255))  # #0F172A
    draw = ImageDraw.Draw(img)

    # Brand gradient (vertical).
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(15 + (91 - 15) * t)
        g = int(23 + (141 - 23) * t)
        b = int(42 + (239 - 42) * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    # Accent ring.
    pad = max(2, size // 16)
    draw.ellipse(
        [(pad, pad), (size - pad, size - pad)],
        outline=(255, 255, 255, 230),
        width=max(2, size // 64 + 1),
    )
    # "C" mark in the centre.
    cx, cy = size // 2, size // 2
    r_inner = size // 4
    draw.arc(
        [(cx - r_inner, cy - r_inner), (cx + r_inner, cy + r_inner)],
        start=35, end=325, fill=(255, 255, 255, 235),
        width=max(2, size // 24),
    )

    # Wordmark.
    try:
        font = ImageFont.truetype("arial.ttf", max(8, size // 6))
        text = "CHERYY"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((size - tw) // 2, size - th - max(2, size // 12)),
            text, fill=(230, 237, 243, 240), font=font,
        )
    except Exception:
        pass

    return img


def _write_icns(out: Path, png_256: bytes) -> None:
    """Write a minimal valid .icns containing one 256x256 PNG (ic08)."""
    entry_type = b"ic08"
    entry = entry_type + struct.pack(">I", len(png_256) + 8) + png_256
    blob = b"icns" + struct.pack(">I", len(entry) + 8) + entry
    out.write_bytes(blob)


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else (
        Path(__file__).resolve().parent.parent / "desktop" / "src-tauri" / "icons"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # PNGs at every size tauri.conf.json lists.
    sizes: list[tuple[str, int]] = [
        ("32x32.png", 32),
        ("128x128.png", 128),
        ("128x128@2x.png", 256),
    ]
    for name, sz in sizes:
        _build_cheryy_icon(sz).save(out_dir / name, format="PNG", optimize=True)

    # Windows ICO (multi-resolution).
    ico = _build_cheryy_icon(256).resize((256, 256))
    ico.save(out_dir / "icon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    # macOS ICNS — minimal valid one-image file with a 256x256 PNG.
    png_256 = _build_cheryy_icon(256).resize((256, 256))
    buf = __import__("io").BytesIO()
    png_256.save(buf, format="PNG")
    _write_icns(out_dir / "icon.icns", buf.getvalue())

    print(f"[cheryy] wrote {len(sizes) + 2} icons to {out_dir}")
    for name, _ in sizes:
        print(f"  - {name}")
    print("  - icon.ico")
    print("  - icon.icns")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
