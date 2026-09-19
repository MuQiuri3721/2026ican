"""D-Fire YOLO11n 训练脚本（HF 镜像 badsaarow/d-fire → YOLO 格式 → ultralytics 训练）。

数据：train/ 7222 图 + txt（YOLO 归一化框）；从中划 5% 做验证。
类别：0=fire 1=smoke（训练前抽样校验，见 verify_class_ids）。
产物：yolo_server/best.pt（拷贝自 runs 目录最优权重，供 local-yolo-service 加载）。

用法：python scripts/yolo/train_dfire.py [--epochs 40] [--data-root <snapshot_dir>]
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DATA_YAML = {
    "path": ".",  # 相对 yaml 所在目录
    "train": "images/train",
    "val": "images/val",
    "names": {0: "fire", 1: "smoke"},
}


def verify_class_ids(labels_dir: Path, sample: int = 200) -> set:
    """抽样校验标注类别 id ∈ {0,1}，防止镜像类别序漂移。"""
    ids = set()
    files = sorted(labels_dir.glob("*.txt"))[:sample]
    for txt in files:
        for line in txt.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts:
                ids.add(int(parts[0]))
    return ids


def prepare(split_root: Path, work_dir: Path, val_ratio: float = 0.05) -> Path:
    """把 D-Fire 的 train/{images,labels|txt} 整理为 ultralytics 目录结构并切出验证集。"""
    images_src = split_root / "train" / "images"
    labels_src = split_root / "train" / "labels"
    if not labels_src.exists():
        labels_src = split_root / "train" / "txt"  # HF 镜像变体命名
    assert images_src.exists() and labels_src.exists(), f"数据结构不符: {split_root}"

    ids = verify_class_ids(labels_src)
    assert ids <= {0, 1}, f"类别 id 异常: {ids}（期望 {{0,1}}）"
    print(f"标注类别 id 校验通过: {ids}")

    images_dir = work_dir / "images"
    labels_dir = work_dir / "labels"
    for sub in ("train", "val"):
        (images_dir / sub).mkdir(parents=True, exist_ok=True)
        (labels_dir / sub).mkdir(parents=True, exist_ok=True)

    jpgs = sorted(images_src.glob("*.jpg"))
    random.seed(42)
    val_ids = set(random.sample(range(len(jpgs)), max(1, int(len(jpgs) * val_ratio))))
    copied = 0
    for index, img in enumerate(jpgs):
        label = labels_src / (img.stem + ".txt")
        if not label.exists():
            continue  # 无标注图跳过（D-Fire 负样本若需保留可换 empty label）
        sub = "val" if index in val_ids else "train"
        shutil.copy2(img, images_dir / sub / img.name)
        shutil.copy2(label, labels_dir / sub / label.name)
        copied += 1
    print(f"整理完成: {copied} 张（val {len(val_ids)}）")

    yaml_path = work_dir / "dfire.yaml"
    yaml_path.write_text(
        "\n".join([f"path: {work_dir.as_posix()}",
                   f"train: {DATA_YAML['train']}", f"val: {DATA_YAML['val']}",
                   "names:", *[f"  {k}: {v}" for k, v in DATA_YAML["names"].items()]]),
        encoding="utf-8")
    return yaml_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="data/dfire")
    parser.add_argument("--work-dir", default="data/dfire_yolo")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=-1)  # -1 = 自动 batch
    args = parser.parse_args()

    snapshot = Path(args.data_root)
    if not (snapshot / "train").exists():
        # data/dfire 下只有 train.tar 时先解包
        tar_path = snapshot / "train.tar"
        assert tar_path.exists(), f"找不到 train/ 或 train.tar: {snapshot}"
        print("解包 train.tar ...")
        import tarfile
        with tarfile.open(tar_path) as tar:
            tar.extractall(snapshot)
    print("数据目录:", snapshot)

    work_dir = Path(args.work_dir).resolve()
    yaml_path = prepare(snapshot, work_dir)
    print("data.yaml:", yaml_path)

    from ultralytics import YOLO
    model = YOLO("yolo11n.pt")  # 官方预训练权重自动下载
    results = model.train(
        data=str(yaml_path), epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=0, project="runs/dfire", name="yolo11n_v1",
        patience=10, plots=True,
    )
    best = Path(results.save_dir) / "weights" / "best.pt"
    target = Path(__file__).resolve().parents[2] / "yolo_server" / "best.pt"
    shutil.copy2(best, target)
    metrics = {k: round(v, 4) for k, v in (results.results_dict or {}).items()}
    print("训练完成 best.pt ->", target)
    print("指标:", metrics)


if __name__ == "__main__":
    main()
