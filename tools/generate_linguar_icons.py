"""Generate deterministic Windows icons for Linguar Hub Main and Trial."""
from pathlib import Path
import math
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 512


def icon(frame, trial=False):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bg = "#4937c9" if trial else "#20242a"
    bg_inner = "#3f2fba" if trial else "#191d22"
    white = "#fffdf5"
    accent = white if trial else "#72c83e"

    # Concept 2: a property roof over a connected operational hub. The slight
    # inset field adds depth while keeping the small Windows icon crisp.
    d.rounded_rectangle((10, 10, 502, 502), radius=105, fill=bg)
    d.rounded_rectangle((24, 24, 488, 488), radius=92, fill=bg_inner)

    # Property roof and chimney.
    d.line((75, 197, 256, 82, 437, 197), fill=accent, width=31,
           joint="curve")
    d.rectangle((360, 101, 398, 166), fill=accent)

    # Six connected departments/workflow points radiating from the hub.
    cx, cy = 256, 292
    nodes = []
    for angle in (-90, -30, 30, 90, 150, 210):
        rad = math.radians(angle)
        x = cx + int(math.cos(rad) * 118)
        y = cy + int(math.sin(rad) * 118)
        nodes.append((x, y))
        d.line((cx, cy, x, y), fill=accent, width=18)

    for i, (x, y) in enumerate(nodes):
        if trial and i == 1:
            # One dotted/open point gives Trial the "still testing" cue.
            d.ellipse((x - 24, y - 24, x + 24, y + 24),
                      outline=white, width=9)
            d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=bg_inner)
        else:
            d.ellipse((x - 25, y - 25, x + 25, y + 25), fill=accent)

    # Strong central ring is the Hub itself.
    d.ellipse((188, 224, 324, 360), fill=white)
    d.ellipse((215, 251, 297, 333), fill=bg_inner)
    return im


def save(name, frame, trial=False):
    im = icon(frame, trial)
    im.save(ROOT / f"{name}.png")
    im.save(ROOT / f"{name}.ico", format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                   (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    save("linguar_hub", "#86f000")
    save("linguar_hub_trial", "#ff7900", trial=True)
