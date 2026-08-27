"""Generate deterministic Windows icons for Linguar Hub Main and Trial."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 512


def icon(frame, trial=False):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((10, 10, 502, 502), radius=105,
                        fill="#090b0a", outline=frame, width=15)
    # Oversized unified restoration badge: Contents forms the left half and
    # Recon forms the right. The broad silhouettes survive 16 px rendering.
    yellow = "#e8f500"
    orange = "#ff7900"
    d.polygon(((54, 142), (172, 67), (260, 111), (260, 171),
               (188, 137), (112, 184), (112, 344), (236, 419), (236, 480),
               (54, 370)), fill=yellow)
    d.polygon(((276, 97), (388, 125), (465, 190), (432, 241),
               (385, 203), (361, 320), (458, 369), (425, 427),
               (276, 480)), fill=orange)
    # Strong black joints keep the two trades legible rather than blending.
    d.line((260, 111, 260, 171), fill="#090b0a", width=17)
    d.line((236, 419, 236, 480), fill="#090b0a", width=17)
    # EMS droplet is the dominant central mark.
    blue = "#2688ff"
    d.polygon(((256, 111), (180, 250), (178, 304), (200, 353),
               (239, 379), (273, 379), (312, 353), (334, 304),
               (332, 250)), fill=blue)
    d.ellipse((178, 252, 334, 390), fill=blue)
    if trial:
        # A compact white corner spark distinguishes Trial without shrinking
        # the primary restoration mark.
        d.polygon(((423, 42), (434, 67), (459, 78), (434, 89),
                   (423, 114), (412, 89), (387, 78), (412, 67)), fill="#ffffff")
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
