"""Run once to generate servpro.ico from the company SVG logo.

Usage:
    python make_icon.py <path-to-source.svg> [output.ico]

If no output path is supplied, writes servpro.ico next to this script.
"""
import io, os, sys

from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image

if len(sys.argv) < 2:
    print("Usage: python make_icon.py <source.svg> [output.ico]")
    sys.exit(1)

SVG = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "servpro.ico")

drawing = svg2rlg(SVG)

# Render at large size first, then downsample
render_size = 512
scale = render_size / max(drawing.width, drawing.height)
drawing.width  *= scale
drawing.height *= scale
drawing.transform = f"scale({scale})"

png_data = renderPM.drawToString(drawing, fmt="PNG")
src = Image.open(io.BytesIO(png_data)).convert("RGBA")

# Crop to square from center
w, h = src.size
side = min(w, h)
left = (w - side) // 2
top  = (h - side) // 2
src  = src.crop((left, top, left + side, top + side))

sizes  = [256, 128, 64, 48, 32, 16]
frames = [src.resize((s, s), Image.LANCZOS) for s in sizes]

frames[0].save(OUT, format="ICO",
               sizes=[(s, s) for s in sizes],
               append_images=frames[1:])
print(f"Saved: {OUT}")
