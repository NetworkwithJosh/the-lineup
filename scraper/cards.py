"""Share images for event pages (1200x630), so a link to an event looks like an invite on LinkedIn, iMessage, Slack.
Needs Pillow. If it's missing, pages fall back to the site-wide image."""
from pathlib import Path

FONTS = Path(__file__).resolve().parent / "fonts"
W, H = 1200, 630
BG, CARD, LINE, INK, SOFT, ACC = (11, 13, 16), (18, 22, 27), (35, 42, 50), (233, 237, 241), (154, 167, 180), (255, 181, 71)

try:
    from PIL import Image, ImageDraw, ImageFont
    _bold = lambda n: ImageFont.truetype(str(FONTS / "Inter-Bold.otf"), n)
    _med = lambda n: ImageFont.truetype(str(FONTS / "Inter-Medium.otf"), n)
    OK = True
except Exception:  # no Pillow or fonts: skip cards
    OK = False


def _wrap(draw, text, font, width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
        lines[-1] += "…"
    return lines


def make(path: Path, title: str, when: str, where: str, tags: str) -> bool:
    if not OK:
        return False
    clean = lambda t: " ".join("".join(c for c in t if ord(c) < 0x2000 or c in "–—…‘’“”•·€£").split())  # Inter has no emoji
    title, where = clean(title), clean(where)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, W - 40, H - 40), radius=28, fill=CARD, outline=LINE, width=2)
    # brand
    d.rounded_rectangle((90, 92, 112, 114), radius=5, fill=ACC)
    d.text((126, 86), "The Lineup", font=_bold(30), fill=INK)
    d.text((W - 90, 90), tags.upper(), font=_med(22), fill=SOFT, anchor="ra")
    # title: shrink to fit in 3 lines
    for size in (68, 60, 52, 46):
        f = _bold(size)
        lines = _wrap(d, title, f, W - 180, 3)
        if len(lines) <= 2 or size == 46:
            break
    y = 170
    for ln in lines:
        d.text((90, y), ln, font=f, fill=INK)
        y += int(size * 1.18)
    # when / where
    y = max(y + 18, 400)
    d.text((90, y), when, font=_bold(34), fill=ACC)
    d.text((90, y + 48), where, font=_med(30), fill=SOFT)
    # call to action
    d.line((90, H - 120, W - 90, H - 120), fill=LINE, width=2)
    d.text((90, H - 100), "Who else is going?  See them and connect at thelineup.dev", font=_med(26), fill=INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=82, optimize=True, progressive=False)
    return True
