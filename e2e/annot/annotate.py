"""在截图上绘制标注：编号圆圈 + 序号徽章（亮黄圈 + 红底白字编号）。"""
from __future__ import annotations
import json, os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(BASE, "shots")
OUT = os.path.join(BASE, "annotated")
os.makedirs(OUT, exist_ok=True)
CIRCLE = (255, 210, 0, 255)
BADGE_BG = (226, 61, 46, 255)
BADGE_FG = (255, 255, 255, 255)

def font(size):
    for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        p = os.path.join(os.environ.get("WIND", r"C:\Windows"), "Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def main():
    boxes = json.load(open(os.path.join(BASE, "boxes.json"), encoding="utf-8"))
    f_badge = font(22)
    for name, marks in boxes.items():
        src = os.path.join(SHOTS, f"{name}.png")
        if not os.path.exists(src) or not marks:
            continue
        im = Image.open(src).convert("RGBA")
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for i, m in enumerate(marks, 1):
            m["n"] = i  # 按可见顺序重编号，保证图上徽章与文档图例一致
            cx, cy, w, h = m["cx"], m["cy"], m["w"], m["h"]
            rx = max(w / 2 + 14, 34)
            ry = max(h / 2 + 10, 26)
            d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=CIRCLE, width=4)
            badge_r = 15
            bx, by = cx + rx - 6, cy - ry - 4
            d.ellipse([bx - badge_r, by - badge_r, bx + badge_r, by + badge_r], fill=BADGE_BG)
            t = str(m["n"])
            tb = d.textbbox((0, 0), t, font=f_badge)
            d.text((bx - (tb[2] - tb[0]) / 2 - tb[0], by - (tb[3] - tb[1]) / 2 - tb[1]), t, font=f_badge, fill=BADGE_FG)
        Image.alpha_composite(im, layer).convert("RGB").save(os.path.join(OUT, f"{name}.png"))
        print(f"  {name}: {len(marks)} 标注", flush=True)

if __name__ == "__main__":
    main()
