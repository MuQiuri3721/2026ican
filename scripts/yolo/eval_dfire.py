"""D-Fire 官方 test 集评测（训练完成后运行）：整理 test/{images,labels} → model.val() → 输出指标。

用法：python scripts/yolo/eval_dfire.py [--data-root data/dfire] [--weights yolo_server/best.pt]
前置：data/dfire/test.tar 已下载并解包出 test/{images,labels}；best.pt 已导出。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def prepare(work_dir: Path) -> Path:
    images_src = Path("data/dfire/test/images")
    labels_src = Path("data/dfire/test/labels")
    assert images_src.exists() and labels_src.exists(), f"test 结构不符（先解包 test.tar）: {images_src.parent}"

    images_dir = work_dir / "images" / "test"
    labels_dir = work_dir / "labels" / "test"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for img in images_src.glob("*.jpg"):
        if img.name.startswith("._"):
            continue
        label = labels_src / (img.stem + ".txt")
        if not label.exists():
            continue
        shutil.copy2(img, images_dir / img.name)
        shutil.copy2(label, labels_dir / label.name)
        count += 1
    print(f"test 集整理: {count} 张")

    yaml_path = work_dir / "dfire_test.yaml"
    yaml_path.write_text(
        "\n".join([f"path: {work_dir.as_posix()}",
                   "train: images/train",  # val 占位（ultralytics 要求键存在，不使用）
                   "val: images/test",
                   "names:", "  0: smoke", "  1: fire"]),
        encoding="utf-8")
    return yaml_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="data/dfire")
    parser.add_argument("--weights", default="yolo_server/best.pt")
    parser.add_argument("--work-dir", default="data/dfire_yolo")
    args = parser.parse_args()

    yaml_path = prepare(Path(args.work_dir).resolve())
    print("评测 yaml:", yaml_path)

    from ultralytics import YOLO
    model = YOLO(args.weights)
    metrics = model.val(data=str(yaml_path), imgsz=640, device=0)
    print("=" * 50)
    print("D-Fire test 评测结果：")
    for key in ("metrics/precision(B)", "metrics/recall(B)", "metrics/mAP50(B)", "metrics/mAP50-95(B)"):
        print(f"  {key}: {metrics.results_dict.get(key)}")


if __name__ == "__main__":
    main()
