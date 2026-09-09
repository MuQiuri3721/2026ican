# -*- coding: utf-8 -*-
"""抓取森林场景 × 人员距离矩阵的真实照片（Bing 图片异步接口）。

类别：森林无火远/近景、森林着火远/近景、林中人远景/近景、消防员扑火(人+火)。
图片仅存 e2e/_real_images/forestpeople/（gitignore，来源网络版权不明不入库）。
用法：python e2e/_forest_fetch.py
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

OUT = Path("e2e/_real_images/forestpeople")
OUT.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    ("forest_far", "原始森林 航拍 远眺 山林"),
    ("forest_near", "森林 近景 树木 林间小路"),
    ("fire_far", "森林火灾 航拍 山火 远景"),
    ("fire_near", "森林 地面火 火焰 树木 近景"),
    ("people_far", "森林 徒步 一群人 远处"),
    ("people_near", "森林里 人物 近景 树林中"),
    ("firefighter", "森林消防员 扑火 火线"),
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
        "User-Agent": UA, "Referer": "https://cn.bing.com/"})
    return urllib.request.urlopen(req, timeout=30).read()


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
            if got >= 3:
                break
            if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                blob = download(url)
            except Exception:
                continue
            if len(blob) < 40_000 or blob[:3] != b"\xff\xd8\xff":
                continue
            try:
                img = Image.open(io.BytesIO(blob))
                img.verify()
                img = Image.open(io.BytesIO(blob))
                if img.width < 600 or img.height < 400:
                    continue
                if img.mode != "RGB":
                    img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, "JPEG", quality=92)
                    blob = buf.getvalue()
            except Exception:
                continue
            name = f"{cat}_{got + 1}.jpg"
            (OUT / name).write_bytes(blob)
            manifest.append({
                "category": cat, "file": f"{name}", "query": word,
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
    return 0 if len({m["category"] for m in manifest}) >= 6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
