# -*- coding: utf-8 -*-
"""
00_normalize_images.py — 把 _raw_images 里的图片统一整理成测试可用的 jpg

做什么：
    1) 原始文件移动到 originals/ 子文件夹备份（不改动、不删除）
    2) 每张图转成 jpg、最长边压到 1600px 以内、单张控制在 4MB 以下
    3) 文件名清理成规整形式：T01.jpg、T10a.jpg ...
    4) 生成/更新 images_manifest.json（文件名、尺寸、大小、哈希）

用法（在 vlm-prep 目录下运行）：
    python scripts/00_normalize_images.py
以后补了新图（如 T11a/T11b），再运行一次即可，已有的不会重复处理。
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")
RAW = ROOT / "data" / "vlm-testcases" / "_raw_images"
ORIG = RAW / "originals"
MANIFEST = RAW / "images_manifest.json"

MAX_SIDE = 1600          # 最长边像素
TARGET_KB = 3800         # 单张大小上限（留余量，接口按4.5MB挡）
CANONICAL = re.compile(r"^(T\d{2}[ab]?)$", re.IGNORECASE)


def canonical_stem(filename: str) -> str:
    """从各种奇怪文件名里提取规范编号，比如 T01.jpg.jpg -> T01。"""
    stem = Path(filename).stem              # T01.jpg
    if CANONICAL.match(stem):               # 已经是 T01
        return stem.upper()
    if CANONICAL.match(Path(stem).stem):    # T01.jpg -> T01
        return Path(stem).stem.upper()
    return None


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def convert_one(src: Path, dst: Path):
    """转 jpg + 缩放 + 控制大小。"""
    img = Image.open(src)
    if getattr(img, "is_animated", False):   # gif 动图取第一帧
        img.seek(0)
    if img.mode != "RGB":                    # 透明通道/灰度等统一转 RGB
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        scale = MAX_SIDE / max(w, h)
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    quality = 90
    while quality >= 40:
        img.save(dst, "JPEG", quality=quality)
        if dst.stat().st_size <= TARGET_KB * 1024:
            return
        quality -= 10
    raise RuntimeError("压缩后仍超过大小上限: %s" % dst.name)


def main():
    ORIG.mkdir(exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) \
        if MANIFEST.exists() else {"images": {}}

    files = [p for p in RAW.iterdir()
             if p.is_file() and p.suffix.lower() in
             (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")]

    done, skipped, problems = [], [], []
    for p in sorted(files):
        stem = canonical_stem(p.name)
        if stem is None:
            problems.append((p.name, "文件名不像 T01/T10a 这种编号，先跳过"))
            continue
        dst = RAW / (stem + ".jpg")
        if dst.exists():
            skipped.append((p.name, "已有 %s，不重复处理" % dst.name))
            continue
        try:
            backup = ORIG / p.name
            if not backup.exists():
                backup.write_bytes(p.read_bytes())
            convert_one(p, dst)
            img = Image.open(dst)
            done.append((p.name, "%s (%dx%d, %dKB)" %
                         (dst.name, img.width, img.height,
                          dst.stat().st_size // 1024)))
            manifest["images"][dst.name] = {
                "sha256_16": sha16(dst),
                "size_kb": dst.stat().st_size // 1024,
                "width": img.width, "height": img.height,
                "normalized_from": p.name,
                "source": None,   # 待你提供图片来源后填入
            }
        except Exception as e:
            problems.append((p.name, "处理失败: %s" % e))

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print("== 标准化完成 ==")
    for name, info in done:
        print("  [转换] %-18s -> %s" % (name, info))
    for name, why in skipped:
        print("  [跳过] %-18s %s" % (name, why))
    for name, why in problems:
        print("  [问题] %-18s %s" % (name, why))
    if not files:
        print("  （文件夹里没有待处理的图片）")
    print("\n清单已更新: %s" % MANIFEST.relative_to(ROOT))
    expect = ["T%02d%s" % (n, s) for n in range(1, 13)
              for s in ("a", "b") if n >= 10] + \
             ["T%02d" % n for n in range(1, 10)]
    missing = [e for e in expect if not (RAW / (e + ".jpg")).exists()]
    if missing:
        print("还缺的编号: %s" % ", ".join(missing))


if __name__ == "__main__":
    main()
