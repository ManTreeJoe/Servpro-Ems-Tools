"""Generate deterministic Windows icons for Linguar Hub Main and Trial."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 512


def icon(frame, trial=False):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((16, 16, 496, 496), radius=108,
                        fill="#090b0a", outline=frame, width=25)
    # Three connecting restoration-cycle segments.
    ring = (104, 74, 408, 404)
    for start, end in ((150, 258), (282, 390), (35, 145)):
        d.arc(ring, start=start, end=end, fill=frame, width=27)
    # Center property.
    d.polygon(((256, 190), (173, 258), (198, 258), (198, 348),
               (314, 348), (314, 258), (339, 258)), fill=frame)
    d.rectangle((238, 292, 274, 348), fill="#090b0a")
    # EMS droplet.
    d.polygon(((256, 51), (220, 116), (224, 144), (243, 164),
               (269, 164), (288, 144), (292, 116)), fill="#2688ff")
    # Contents box.
    yellow = "#e8f500"
    d.polygon(((61, 340), (126, 303), (191, 340), (126, 377)),
              outline=yellow, width=18)
    d.line((61, 340, 61, 411, 126, 449, 191, 411, 191, 340),
           fill=yellow, width=18, joint="curve")
    d.line((126, 377, 126, 449), fill=yellow, width=18)
    # Recon hammer.
    orange = "#ff7900"
    # T-shaped hammer: diagonal head, perpendicular handle.
    d.line((378, 315, 448, 385), fill=orange, width=34)
    d.line((410, 374, 340, 444), fill=orange, width=24)
    if trial:
        d.polygon(((434, 55), (445, 79), (469, 90), (445, 101),
                   (434, 125), (423, 101), (399, 90), (423, 79)), fill=orange)
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
