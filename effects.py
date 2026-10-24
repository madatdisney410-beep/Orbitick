"""Animated fills for the box panels: shooting stars, galaxy, aurora, embers, or your own image.

Each effect pre-builds its expensive parts once per panel size and colour scheme
(star fields, nebula clouds, aurora ribbons, glow sprites) and then only moves,
crops or pastes them per frame, so animating stays cheap enough to run over any app.
"""
import bisect
import colorsys
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

EFFECTS = [
    ("none", "Solid"),
    ("stars", "Shooting stars"),
    ("galaxy", "Galaxy"),
    ("aurora", "Aurora"),
    ("embers", "Embers"),
    ("custom", "Custom image"),
]
FITS = [("fill", "Fill"), ("stretch", "Stretch"), ("fit", "Fit")]
MEDIA_TYPES = [("Images and animations", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.apng"), ("All files", "*.*")]
MAX_ANIMATION_SECONDS = 15
MAX_FRAMES = 150  # longer animations are thinned out evenly, to keep memory in check


def _frame_ms(info):
    # Like browsers, treat missing or near-zero frame delays as 100 ms.
    ms = info.get("duration") or 0
    return ms if ms >= 20 else 100


def inspect_media(path):
    """(frames, seconds) of an image or animation. Raises ValueError with a message for the user."""
    try:
        with Image.open(path) as im:
            frames = getattr(im, "n_frames", 1)
            total = 0
            if frames > 1:
                for i in range(frames):
                    im.seek(i)
                    total += _frame_ms(im.info)
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError("This file could not be opened as an image or animation. "
                         "Supported formats are PNG, JPG, BMP, GIF, WebP and APNG.")
    seconds = total / 1000
    if seconds > MAX_ANIMATION_SECONDS:
        raise ValueError(f"This animation is {seconds:.1f} seconds long. "
                         f"Animations can be up to {MAX_ANIMATION_SECONDS} seconds.")
    return frames, seconds


def _fit(frame, size, mode, bg):
    """Size one RGBA frame to the panel: fill (crop to cover), stretch, or fit (whole image)."""
    if mode == "stretch":
        frame = frame.resize(size, Image.LANCZOS)
        offset = (0, 0)
    elif mode == "fit":
        frame = ImageOps.contain(frame, size, Image.LANCZOS)
        offset = ((size[0] - frame.width) // 2, (size[1] - frame.height) // 2)
    else:
        frame = ImageOps.fit(frame, size, Image.LANCZOS)
        offset = (0, 0)
    canvas = Image.new("RGB", size, bg)
    canvas.paste(frame, offset, frame)
    return canvas


def _hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _hue(rgb, degrees, sat=None, val=None):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    r, g, b = colorsys.hsv_to_rgb((h + degrees / 360) % 1, s if sat is None else sat, v if val is None else val)
    return round(r * 255), round(g * 255), round(b * 255)


def _gradient(size, top, bottom):
    w, h = size
    mask = Image.linear_gradient("L").resize((w, h))
    return Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), mask)


def _glow_sprite(radius):
    d = max(3, round(radius * 4))
    sprite = Image.new("L", (d, d), 0)
    c = d / 2
    ImageDraw.Draw(sprite).ellipse((c - radius, c - radius, c + radius, c + radius), fill=255)
    return sprite.filter(ImageFilter.GaussianBlur(radius * 0.7))


def _star_masks(size, k, density, seed):
    """Two interleaved star fields, cross-faded each frame so the stars twinkle."""
    w, h = size
    rng = random.Random(seed)
    masks = [Image.new("L", size, 0), Image.new("L", size, 0)]
    draws = [ImageDraw.Draw(m) for m in masks]
    for i in range(int(w * h / 1400 * density)):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.choice([0.5, 0.5, 0.5, 0.8, 0.8, 1.2]) * k
        value = rng.randint(90, 255)
        draws[i % 2].ellipse((x - r, y - r, x + r, y + r), fill=value)
    for _ in range(int(3 * density) + 1):  # a few soft, bright ones
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        sprite = _glow_sprite(2.2 * k)
        masks[rng.randint(0, 1)].paste(255, (round(x), round(y)), sprite)
    return masks


def _twinkle(img, masks, color, t, strength):
    for i, mask in enumerate(masks):
        a = (0.55 + 0.45 * math.sin(t * 1.6 + i * math.pi)) * strength
        img.paste(color, (0, 0, *img.size), mask.point(lambda v: round(v * a)))


class Effects:
    def __init__(self):
        self._assets = {}
        self._media_info = {}

    def is_animated(self, s):
        """Does this effect need redrawing every frame?"""
        if s["panel_effect"] == "none":
            return False
        if s["panel_effect"] != "custom":
            return True
        path = s["custom_bg"]
        try:
            key = (path, os.path.getmtime(path))
        except OSError:
            return False
        if key not in self._media_info:
            try:
                self._media_info[key] = inspect_media(path)
            except ValueError:
                self._media_info[key] = (1, 0)
        return self._media_info[key][0] > 1

    def frame(self, s, size, k, t):
        """The panel fill (RGB, `size`) for effect s['panel_effect'] at time t (seconds)."""
        name = s["panel_effect"] if s["panel_effect"] in dict(EFFECTS) else "none"
        strength = max(0.0, min(1.0, s["effect_strength"]))
        key = (name, size, k, s["bg"], s["fg"], s["accent"], s["warn"], round(strength, 2))
        if name == "custom":
            try:
                key += (s["custom_bg"], os.path.getmtime(s["custom_bg"]), s["custom_fit"])
            except OSError:
                name, key = "none", key[1:]  # file gone: fall back to a plain panel
        assets = self._assets.get(key)
        if assets is None:
            # Custom animations are the heavy ones, so keep only a panel's worth each.
            limit = 4 if name == "custom" else 8  # one per box panel
            if sum(1 for k_ in self._assets if k_[0] == name) >= limit or len(self._assets) > 10:
                for old in [k_ for k_ in self._assets if k_[0] == name or len(self._assets) > 10]:
                    del self._assets[old]
            assets = self._assets[key] = self._build(name, size, k, s, strength)
        return getattr(self, f"_{name}")(assets, t * s["effect_speed"]) if name != "none" else assets["base"]

    # ---- building (once per size / colours) ----

    def _build(self, name, size, k, s, strength):
        w, h = size
        bg, fg, accent, warn = (_hex(s[c]) for c in ("bg", "fg", "accent", "warn"))
        a = {"size": size, "k": k, "strength": strength,
             "base": _gradient(size, _mix(bg, fg, 0.08), bg)}
        if name == "none":
            return a
        a["stars"] = _star_masks(size, k, 0.6 + strength, seed=7)
        a["star_color"] = _mix(fg, accent, 0.25)

        if name == "stars":
            a["base"] = _gradient(size, _mix(bg, accent, 0.10), _mix(bg, (0, 0, 0), 0.25))
            a["head"] = _glow_sprite(2.6 * k)
            a["meteor_color"] = _mix(fg, accent, 0.35)

        elif name == "galaxy":
            pad = round(28 * k)
            big = (w + 2 * pad, h + 2 * pad)
            rng = random.Random(11)
            dark = _mix(bg, (0, 0, 0), 0.3)
            nebula = _gradient(big, _mix(dark, accent, 0.06), dark).convert("RGBA")
            palette = [accent, _hue(accent, 55), _hue(accent, -70), _hue(accent, 150, 0.6, 0.8)]
            clouds = Image.new("RGBA", big, (0, 0, 0, 0))
            draw = ImageDraw.Draw(clouds)
            for i in range(18):
                cw, ch = rng.uniform(0.25, 0.75) * big[0], rng.uniform(0.15, 0.5) * big[1]
                cx, cy = rng.uniform(0, big[0]), rng.uniform(0, big[1])
                color = palette[i % len(palette)]
                draw.ellipse((cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2),
                             fill=(*color, round(rng.uniform(25, 70) * (0.4 + strength))))
            # A bright diagonal band, like the core of a spiral galaxy.
            band = Image.new("RGBA", big, (0, 0, 0, 0))
            ImageDraw.Draw(band).ellipse((big[0] * 0.1, big[1] * 0.42, big[0] * 0.9, big[1] * 0.58),
                                         fill=(*_mix(fg, accent, 0.5), round(90 * strength)))
            band = band.rotate(-22, Image.BICUBIC, center=(big[0] / 2, big[1] / 2))
            clouds.alpha_composite(band)
            nebula.alpha_composite(clouds.filter(ImageFilter.GaussianBlur(20 * k)))
            a["nebula"] = nebula.convert("RGB")
            a["pad"] = pad

        elif name == "aurora":
            a["base"] = _gradient(size, _mix(bg, (0, 0, 0), 0.3), _mix(bg, accent, 0.06))
            a["ribbons"] = []
            for seed, (hue, speed, height) in enumerate([(35, 9, 0.34), (-45, -5, 0.5)]):
                mask = Image.new("L", (w, h), 0)
                draw = ImageDraw.Draw(mask)
                for x in range(w):
                    p = 2 * math.pi * x / w  # periodic across the width, so it tiles seamlessly
                    yc = h * (height + 0.09 * math.sin(2 * p + seed) + 0.025 * math.sin(5 * p + 2 * seed))
                    thick = h * (0.22 + 0.10 * math.sin(3 * p + seed * 1.7))
                    for length, value in ((1.0, 70), (0.6, 130), (0.28, 220)):
                        draw.line((x, yc, x, yc + thick * length), fill=value)
                # Blur three copies side by side and keep the middle, so the blur wraps around too.
                wide = Image.new("L", (w * 3, h))
                for i in range(3):
                    wide.paste(mask, (w * i, 0))
                mask = wide.filter(ImageFilter.GaussianBlur(5 * k)).crop((w, 0, 2 * w, h))
                mask = mask.point(lambda v: round(v * (0.35 + 0.65 * strength)))
                tile = Image.new("L", (w * 2, h))
                tile.paste(mask, (0, 0))
                tile.paste(mask, (w, 0))
                color = _gradient(size, _hue(accent, hue), _hue(accent, hue + 60, val=0.6))
                a["ribbons"].append((tile, color, speed * k))

        elif name == "custom":
            # Decode once, fit to the panel and blend with its colour (strength = how much image shows).
            frames, ends, total = [], [], 0
            try:
                with Image.open(s["custom_bg"]) as im:
                    count = getattr(im, "n_frames", 1)
                    step = max(1, math.ceil(count / MAX_FRAMES))
                    durations = []
                    for i in range(count):
                        im.seek(i)
                        durations.append(_frame_ms(im.info))
                    for i in range(0, count, step):
                        im.seek(i)
                        fitted = _fit(im.convert("RGBA"), size, s["custom_fit"], bg)
                        frames.append(Image.blend(a["base"], fitted, 0.15 + 0.85 * strength))
                        total += sum(durations[i:i + step])
                        ends.append(total)
            except (OSError, ValueError):
                frames, ends, total = [a["base"]], [1], 1
            a.update(frames=frames, ends=ends, total=max(1, total))

        elif name == "embers":
            a["base"] = _gradient(size, _mix(bg, (0, 0, 0), 0.25), _mix(bg, warn, 0.12))
            a["sprites"] = [_glow_sprite(r * k) for r in (1.2, 1.8, 2.6)]
            rng = random.Random(5)
            a["particles"] = [dict(x=rng.uniform(0, w), speed=rng.uniform(14, 34) * k, phase=rng.uniform(0, 1000),
                                   sway=rng.uniform(3, 10) * k, freq=rng.uniform(0.4, 1.2), size=rng.randint(0, 2),
                                   flicker=rng.uniform(0, 6))
                              for _ in range(int(16 + 26 * strength))]
            a["ember_color"] = _mix(warn, (255, 214, 150), 0.35)
        return a

    # ---- per frame ----

    def _custom(self, a, t):
        if len(a["frames"]) == 1:
            return a["frames"][0]
        ms = (t * 1000) % min(a["total"], MAX_ANIMATION_SECONDS * 1000)
        return a["frames"][min(len(a["frames"]) - 1, bisect.bisect_right(a["ends"], ms))]


    def _stars(self, a, t):
        img = a["base"].copy()
        w, h = a["size"]
        k = a["k"]
        _twinkle(img, a["stars"], a["star_color"], t, 0.9)
        streaks = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(streaks)
        direction = (-math.cos(math.radians(32)), math.sin(math.radians(32)))  # falling down-left
        for i in range(3):
            period, life = 2.3 + i * 0.7, 1.2
            cycle, phase = divmod(t + i * 1.1, period)
            if phase > life:
                continue
            rng = random.Random(i * 7919 + int(cycle))
            u = phase / life
            sx, sy = rng.uniform(0.45, 1.05) * w, rng.uniform(-0.1, 0.45) * h
            travel = 0.8 * max(w, h)
            hx, hy = sx + direction[0] * travel * u, sy + direction[1] * travel * u
            fade = math.sin(math.pi * u)
            tail = 80 * k * (0.6 + 0.4 * fade)
            for j in range(12):
                f0, f1 = j / 12, (j + 1) / 12
                draw.line((hx - direction[0] * tail * f0, hy - direction[1] * tail * f0,
                           hx - direction[0] * tail * f1, hy - direction[1] * tail * f1),
                          fill=round(255 * fade * (1 - f0) * a["strength"] ** 0.5),
                          width=max(1, round(2 * k * (1 - f0))))
            head = a["head"]
            streaks.paste(round(255 * fade), (round(hx - head.width / 2), round(hy - head.height / 2)), head)
        img.paste(a["meteor_color"], (0, 0, w, h), streaks.filter(ImageFilter.GaussianBlur(0.6 * k)))
        return img

    def _galaxy(self, a, t):
        w, h = a["size"]
        pad = a["pad"]
        ox = pad + pad * math.sin(t * 0.11)
        oy = pad + pad * math.cos(t * 0.08)
        img = a["nebula"].crop((round(ox), round(oy), round(ox) + w, round(oy) + h))
        _twinkle(img, a["stars"], a["star_color"], t, 1.0)
        return img

    def _aurora(self, a, t):
        img = a["base"].copy()
        w, h = a["size"]
        _twinkle(img, a["stars"], a["star_color"], t, 0.5)
        for tile, color, speed in a["ribbons"]:
            off = round(t * speed) % w
            img.paste(color, (0, 0), tile.crop((off, 0, off + w, h)))
        return img

    def _embers(self, a, t):
        img = a["base"].copy()
        w, h = a["size"]
        k = a["k"]
        glow = Image.new("L", (w, h), 0)
        for p in a["particles"]:
            span = h + 30 * k
            y = h + 15 * k - ((t * p["speed"] + p["phase"]) % span)
            x = (p["x"] + p["sway"] * math.sin(t * p["freq"] + p["phase"])) % w
            bright = (0.65 + 0.35 * math.sin(t * 6 + p["flicker"])) * min(1.0, max(0.0, y / (h * 0.55)))
            sprite = a["sprites"][p["size"]]
            glow.paste(round(255 * bright), (round(x - sprite.width / 2), round(y - sprite.height / 2)), sprite)
        img.paste(a["ember_color"], (0, 0, w, h), glow)
        return img
