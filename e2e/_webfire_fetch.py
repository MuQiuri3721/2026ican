# -*- coding: utf-8 -*-
"""联网抓取不同火情类型的真实照片（Bing 图片异步接口；百度 acjson 已反爬拒绝）。

六类场景：大规模林火/中火线/小火堆/夜间火/阴燃浓烟/无火对照。
图片仅存 e2e/_real_images/webfire/（gitignore，来源网络版权不明不入库）。
用法：python e2e/_webfire_fetch.py
"""
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path("e2e/_real_images/webfire")
OUT.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    ("large", "大规模森林火灾 航拍 火线 浓烟"),
    ("medium", "森林火灾 山火 火线燃烧"),
    ("small", "草地火 火堆 地面小火"),
    ("night", "夜间森林火灾 火光"),
    ("smolder", "森林火灾 浓烟 阴燃"),
    ("nofire", "绿色森林 航拍 无人机"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def bing_images(word: str, count: int = 35) -> list:
    query = urllib.parse.urlencode({"q": word, "first": 0, "count": count, "mmasync": 1})
    req = urllib.request.Request(
        f"https://cn.bing.com/images/async?{query}",
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
                 "Referer": "https://cn.bing.com/images/search"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    murls = re.findall(r"murl&quot;:&quot;(.*?)&quot;", raw)
    if not murls:
        murls = re.findall(r'"murl":"(.*?)"', raw)
    return [html.unescape(u) for u in murls]


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://image.baidu.com/"})
    return urllib.request.urlopen(req, timeout=30).read()


def looks_like_image(blob: bytes) -> bool:
    return blob[:3] == b"\xff\xd8\xff" or blob[:8] == b"\x89PNG\r\n\x1a\n"


def main() -> int:
    from PIL import Image
    manifest = []
    for cat, word in CATEGORIES:
        try:
            items = bing_images(word)
        except Exception as error:
            print(f"[{cat}] 搜索失败: {error}")
            continue
        got = 0
        for url in items:
            if got >= 2:
                break
            if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                blob = download(url)
            except Exception:
                continue
            if len(blob) < 30_000 or not looks_like_image(blob):
                continue
            try:
                img = Image.open(io.BytesIO(blob))
                img.verify()
                img = Image.open(io.BytesIO(blob))
                if img.width < 500 or img.height < 350:
                    continue
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, "JPEG", quality=92)
                    blob = buf.getvalue()
            except Exception:
                continue
            name = f"{cat}_{got + 1}.jpg"
            (OUT / name).write_bytes(blob)
            manifest.append({
                "category": cat, "file": f"webfire/{name}", "query": word,
                "source_url": url, "width": img.width, "height": img.height,
                "bytes": len(blob),
            })
            got += 1
            time.sleep(0.4)
        print(f"[{cat}] 抓到 {got} 张 (查询: {word})")
        time.sleep(1.0)
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"共 {len(manifest)} 张 → {OUT}/manifest.json")
    return 0 if len({m["category"] for m in manifest}) >= 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
