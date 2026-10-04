#!/usr/bin/env python3
"""Build the browser extension for Chrome/Edge and Firefox. Standard library only.

    python3 tools/build_extension.py           # -> build/extension/{chrome,firefox}/ + dist/*.zip

The two builds share every source file in extension/src and differ only in the
manifest and in which page hosts the audio:

  chrome   Manifest V3. A service worker cannot play audio, so sw.js opens an
           offscreen document (offscreen.html) that does.
  firefox  Manifest V2 with a persistent background page (background.html).
           Firefox's MV3 background is an event page that is unloaded when
           idle, which would cut the stream; MV2 remains fully supported there.

Load build/extension/chrome via chrome://extensions > Load unpacked, or
build/extension/firefox via about:debugging > Load Temporary Add-on.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "extension", "src")
OUT = os.path.join(ROOT, "build", "extension")
DIST = os.path.join(ROOT, "dist")

CHROME_ONLY = {"sw.js", "offscreen.html"}
FIREFOX_ONLY = {"background.html"}

# Default stations' stream and metadata hosts: a real spectrum (Web Audio needs
# CORS or a host permission) and now-playing titles. User-added stations ask
# for their own host at runtime.
HOSTS = [
    "https://*.somafm.com/*",
    "https://*.plaza.one/*",
    "https://*.radioparadise.com/*",
    "https://*.kexp.org/*",
    "https://kexp.streamguys1.com/*",
    "https://listen.reyfm.de/*",
]
OPTIONAL_HOSTS = ["https://*/*", "http://*/*"]

DESCRIPTION = ("A retro hi-fi internet radio with a live spectrum analyser: commercial-free "
               "stations from SomaFM, Nightwave Plaza, Radio Paradise and KEXP.")
ICON_SIZES = (16, 32, 48, 128)


def version() -> str:
    with open(os.path.join(ROOT, "termbeat", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)


def icons() -> dict:
    return {str(s): f"icons/icon-{s}.png" for s in ICON_SIZES}


def chrome_manifest(ver: str) -> dict:
    return {
        "manifest_version": 3,
        "name": "termbeat",
        "version": ver,
        "description": DESCRIPTION,
        "icons": icons(),
        "action": {"default_popup": "popup.html", "default_title": "termbeat", "default_icon": icons()},
        "background": {"service_worker": "sw.js", "type": "module"},
        "options_page": "options.html",
        "permissions": ["storage", "offscreen"],
        "host_permissions": HOSTS,
        "optional_host_permissions": OPTIONAL_HOSTS,
        "minimum_chrome_version": "116",
    }


def firefox_manifest(ver: str) -> dict:
    return {
        "manifest_version": 2,
        "name": "termbeat",
        "version": ver,
        "description": DESCRIPTION,
        "icons": icons(),
        "browser_action": {"default_popup": "popup.html", "default_title": "termbeat", "default_icon": icons()},
        "background": {"page": "background.html", "persistent": True},
        "options_ui": {"page": "options.html", "open_in_tab": True},
        "permissions": ["storage"] + HOSTS,
        "optional_permissions": OPTIONAL_HOSTS,
        "browser_specific_settings": {
            "gecko": {
                "id": "termbeat@aryangarg-beep.github.io",
                "strict_min_version": "115.0",
                "data_collection_permissions": {"required": ["none"]},
            }
        },
    }


# ------------------------------------------------------------------- icons

def _png(width: int, height: int, pixels) -> bytes:
    """Encode RGBA rows as a PNG."""
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def draw_icon(size: int) -> bytes:
    """The deck in miniature: an LCD panel with five spectrum bars, drawn at 4x
    and box-filtered down so edges are anti-aliased at every size."""
    ss = 4
    n = size * ss
    frame, panel = (70, 95, 145), (6, 20, 12)
    green, amber = (55, 255, 95), (255, 210, 40)
    heights = (0.45, 0.8, 0.6, 0.95, 0.35)
    radius = n * 0.18
    border = max(ss, n * 0.06)
    inset = n * 0.17
    gap = n * 0.035
    bar_w = (n - 2 * inset - gap * 4) / 5

    def inside_round(x, y, pad, r):
        lo, hi = pad, n - pad
        if not (lo <= x < hi and lo <= y < hi):
            return False
        cx = min(max(x, lo + r), hi - r)
        cy = min(max(y, lo + r), hi - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    big = [[(0, 0, 0, 0)] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            px, py = x + 0.5, y + 0.5
            if not inside_round(px, py, 0, radius):
                continue
            col = frame
            if inside_round(px, py, border, radius - border):
                col = panel
                for b, h in enumerate(heights):
                    x0 = inset + b * (bar_w + gap)
                    top = n - inset - h * (n - 2 * inset)
                    if x0 <= px < x0 + bar_w and top <= py < n - inset:
                        col = amber if py < top + max(ss, n * 0.06) else green
            big[y][x] = col + (255,)
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            acc = [0, 0, 0, 0]
            for dy in range(ss):
                for dx in range(ss):
                    r, g, b, a = big[y * ss + dy][x * ss + dx]
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            a = acc[3]
            row.extend([acc[0] // a, acc[1] // a, acc[2] // a, a // (ss * ss)] if a else [0, 0, 0, 0])
        rows.append(row)
    return _png(size, size, rows)


# ------------------------------------------------------------------- build

def build(target: str, manifest: dict, skip: set) -> str:
    dest = os.path.join(OUT, target)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(SRC, dest, ignore=lambda d, names: [n for n in names if n in skip])
    os.makedirs(os.path.join(dest, "icons"), exist_ok=True)
    for s in ICON_SIZES:
        with open(os.path.join(dest, "icons", f"icon-{s}.png"), "wb") as f:
            f.write(draw_icon(s))
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.makedirs(DIST, exist_ok=True)
    archive = os.path.join(DIST, f"termbeat-{target}-{manifest['version']}.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(dest):
            for name in sorted(files):
                path = os.path.join(base, name)
                z.write(path, os.path.relpath(path, dest))
    return archive


def main() -> int:
    check = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "export_stations.py"), "--check"])
    if check.returncode:
        return 1
    ver = version()
    for target, manifest, skip in (("chrome", chrome_manifest(ver), FIREFOX_ONLY),
                                   ("firefox", firefox_manifest(ver), CHROME_ONLY)):
        print(f"{target:8} {build(target, manifest, skip)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
