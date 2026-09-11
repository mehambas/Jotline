"""Create the small terminal demo used in the README."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "jotline-demo.gif"
OUT.parent.mkdir(exist_ok=True)

font_path = "/System/Library/Fonts/Menlo.ttc"
try:
    font = ImageFont.truetype(font_path, 23, index=0)
    bold = ImageFont.truetype(font_path, 24, index=1)
except OSError:
    font = ImageFont.load_default()
    bold = font

BG = (39, 42, 53)
FG = (242, 242, 242)
CYAN = (126, 220, 255)
MAGENTA = (194, 153, 255)
YELLOW = (246, 246, 120)
GREEN = (145, 220, 150)
DIM = (155, 158, 168)


def frame(lines, cursor=None, delay=900):
    image = Image.new("RGB", (980, 470), BG)
    draw = ImageDraw.Draw(image)
    x, y, gap = 26, 24, 42
    for row, runs in enumerate(lines):
        xx = x
        for text, color, face in runs:
            draw.text((xx, y + row * gap), text, font=face, fill=color)
            xx += draw.textlength(text, font=face)
        if cursor == row:
            draw.rectangle((xx + 2, y + row * gap + 2, xx + 5, y + row * gap + 27), fill=FG)
    draw.text((26, 425), "Temporary · not saved · F1 help · Ctrl+Q quit", font=font, fill=DIM)
    image.info["duration"] = delay
    return image


frames = [
    frame([[('$ ', DIM, font), ('jotline -t', FG, font)]], delay=1100),
    frame([[('', FG, font)]], delay=700),
    frame([[('# Jotline', CYAN, font)]], cursor=0, delay=550),
    frame([[('# Jotline scratchpad', CYAN, font)]], cursor=0, delay=850),
    frame([[('Jotline scratchpad', CYAN, bold)], [('', FG, font)]], cursor=1, delay=950),
    frame([[('Jotline scratchpad', CYAN, bold)], [('', FG, font)],
           [('Write notes without leaving the terminal.', FG, font)]], cursor=2, delay=900),
    frame([[('Jotline scratchpad', CYAN, bold)], [('', FG, font)],
           [('Write ', FG, font), ('**bold**', FG, bold), (', ', FG, font),
            ('*italic*', FG, font), (', and ', FG, font), ('`code`', YELLOW, font)]], cursor=2, delay=650),
    frame([[('Jotline scratchpad', CYAN, bold)], [('', FG, font)],
           [('Write ', FG, font), ('**bold**', FG, font), (', ', FG, font),
            ('*italic*', FG, font), (', and ', FG, font), ('`code`', FG, font)]], delay=1250),
    frame([[('Jotline scratchpad', CYAN, bold)], [('', FG, font)],
           [('Write ', FG, font), ('bold', FG, bold), (', ', FG, font),
            ('italic', FG, font), (', and ', FG, font), ('code', YELLOW, font)]], delay=1500),
    frame([[('Jotline scratchpad', CYAN, bold)], [('', FG, font)],
           [('## Today', FG, font)]], cursor=2, delay=700),
    frame([[('Jotline scratchpad', CYAN, bold)], [('Today', MAGENTA, bold)],
           [('', FG, font)]], delay=1000),
    frame([[('Jotline scratchpad', CYAN, bold)], [('Today', MAGENTA, bold)],
           [('- [ ] Review the README', FG, font)]], cursor=2, delay=750),
    frame([[('Jotline scratchpad', CYAN, bold)], [('Today', MAGENTA, bold)],
           [('☐ Review the README', FG, font)]], delay=900),
    frame([[('Jotline scratchpad', CYAN, bold)], [('Today', MAGENTA, bold)],
           [('☐ Review the README', FG, font)],
           [('- [x] Ship v0.1.0', FG, font)]], cursor=3, delay=750),
    frame([[('Jotline scratchpad', CYAN, bold)], [('Today', MAGENTA, bold)],
           [('☐ Review the README', FG, font)],
           [('☑ Ship v0.1.0', GREEN, font)]], delay=1600),
]
frames[0].save(OUT, save_all=True, append_images=frames[1:], loop=0, duration=[f.info["duration"] for f in frames], optimize=True)
print(OUT)
