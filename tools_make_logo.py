"""Regenerate the app logo (icon.png + splash.png) — refined infinity mark.

Core identity: the infinity symbol (one app, every provider), redrawn as a
smooth mathematical lemniscate stroke — replaces the noisy scratched bitmap.
White stroke on the indigo -> violet gradient rounded square (matches the
app's M3 indigo seed), plus the small sparkle accent. Drawn at 4x
supersampling, downsampled for smooth edges.

splash.png is the mark at ~42% width, centered on the solid #101418 splash
background (matches [tool.flet.splash] colors). The old transparent,
edge-to-edge mark overflowed on Android (12+ centers/scales the image and
legacy launch_background uses center gravity) — full-bleed + small mark
fixes scaling on every density.

Run: python tools_make_logo.py  (from the project root)
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

SS = 4  # supersample factor
FINAL = 1024
S = FINAL * SS

# Indigo seed (app theme) -> violet depth.
C1 = (79, 70, 229)    # #4F46E5 indigo
C2 = (124, 58, 237)   # #7C3AED violet
WHITE = (255, 255, 255, 255)


def gradient_square(size: int, radius: int) -> Image.Image:
    """Vertical indigo->violet gradient masked to a rounded square (RGBA)."""
    base = Image.new("RGB", (size, size))
    px = base.load()
    for y in range(size):
        t = y / (size - 1)
        # Ease the gradient slightly (smoothstep) for a softer falloff.
        t = t * t * (3 - 2 * t)
        r = int(C1[0] + (C2[0] - C1[0]) * t)
        g = int(C1[1] + (C2[1] - C1[1]) * t)
        b = int(C1[2] + (C2[2] - C1[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    return out


def lemniscate_points(cx: float, cy: float, w: float, steps: int = 1200):
    """Bernoulli lemniscate (figure-eight) scaled to width w, centered cx,cy.

    x = a*cos t / (1 + sin² t), y = a*sin t cos t / (1 + sin² t)
    Y is flipped (screen coords): the left loop dips like the classic mark.
    """
    a = w / (2 * (1 + 0.25)) * 1.9  # normalize so the mark spans ~w
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        den = 1 + math.sin(t) ** 2
        x = a * math.cos(t) / den
        y = a * math.sin(t) * math.cos(t) / den
        pts.append((cx + x, cy - y))
    return pts


def draw_mark(canvas: Image.Image, cx: float, cy: float, w: float) -> None:
    """Smooth white infinity stroke + sparkle accent, centered at cx,cy."""
    stroke = w * 0.115
    # Soft drop shadow for depth (subtle, blurred, offset down).
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for x, y in lemniscate_points(cx, cy + stroke * 0.55, w):
        sd.ellipse(
            [x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2],
            fill=(20, 10, 60, 70),
        )
    shadow = shadow.filter(ImageFilter.GaussianBlur(stroke * 0.45))
    canvas.alpha_composite(shadow)
    # Stroke: dense filled circles along the lemniscate — smooth, uniform.
    d = ImageDraw.Draw(canvas)
    for x, y in lemniscate_points(cx, cy, w):
        d.ellipse(
            [x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2],
            fill=WHITE,
        )
    # Sparkle at the top-right loop (4-point concave star) — AI accent.
    sr = w * 0.13
    scx, scy = cx + w * 0.36, cy - w * 0.36
    q = sr * 0.30
    d.polygon(
        [
            (scx, scy - sr), (scx + q, scy - q),
            (scx + sr, scy), (scx + q, scy + q),
            (scx, scy + sr), (scx - q, scy + q),
            (scx - sr, scy), (scx - q, scy - q),
        ],
        fill=WHITE,
    )


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))  # script lives in the project root

    # icon.png — gradient rounded square, infinity mark centered.
    icon = gradient_square(S, radius=int(S * 0.225))
    draw_mark(icon, S * 0.5, S * 0.52, S * 0.62)
    icon = icon.resize((FINAL, FINAL), Image.LANCZOS)
    icon.save(os.path.join(root, "assets", "icon.png"))

    # splash.png — mark at ~42% width on the solid splash background.
    splash = Image.new("RGBA", (S, S), (16, 20, 24, 255))  # #101418
    draw_mark(splash, S * 0.5, S * 0.48, S * 0.42)
    splash = splash.resize((FINAL, FINAL), Image.LANCZOS)
    splash.save(os.path.join(root, "assets", "splash.png"))

    print("Wrote assets/icon.png and assets/splash.png")


if __name__ == "__main__":
    main()
