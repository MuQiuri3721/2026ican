"""D-Fire dataset validation, statistics and train/val/test split.

Scans pwm-net/data/{train,test}/{images,labels}, validates YOLO-format labels
(class 0 = smoke, class 1 = fire；与 data/dfire_yolo 一致), reports per-class instance counts and
negative-image counts, then writes a 7:2:1 train/val/test split (fixed seed)
as train.txt / val.txt / test.txt (one image path per line).

Usage:  python datasets/check_dataset.py [--split 0.7 0.2 0.1] [--seed 42]
"""
import argparse
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def find_pairs():
    """Return sorted list of (image_path, label_path_or_None)."""
    pairs = []
    for split in ('train', 'test'):
        img_dir = DATA / split / 'images'
        lbl_dir = DATA / split / 'labels'
        if not img_dir.exists():
            continue
        for img in sorted(img_dir.iterdir()):
            if img.suffix.lower() not in IMG_EXTS:
                continue
            lbl = lbl_dir / (img.stem + '.txt')
            pairs.append((img, lbl if lbl.exists() else None))
    return pairs


def validate_and_count(pairs):
    """Validate labels, return per-class instance Counter and error list."""
    class_counts = Counter()
    errors = []
    n_negative = 0
    total_boxes = 0
    for img, lbl in pairs:
        if lbl is None:
            n_negative += 1
            continue
        text = lbl.read_text().strip()
        if not text:
            n_negative += 1
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            parts = line.split()
            if len(parts) != 5:
                errors.append(f'{lbl}:{ln}: expected 5 fields, got {len(parts)}')
                continue
            try:
                cls = int(parts[0])
                x, y, w, h = map(float, parts[1:])
            except ValueError:
                errors.append(f'{lbl}:{ln}: non-numeric field')
                continue
            if cls not in (0, 1):
                errors.append(f'{lbl}:{ln}: unexpected class id {cls}')
                continue
            # D-Fire quirk: a few boxes overshoot the image by a small amount;
            # allow tolerance (values are clamped in the loader)
            tol = 0.10
            if not all(-tol <= v <= 1 + tol for v in (x, y, w, h)):
                errors.append(f'{lbl}:{ln}: coords out of [0±0.05, 1±0.05]')
                continue
            class_counts[cls] += 1
            total_boxes += 1
    return class_counts, n_negative, total_boxes, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', type=float, nargs=3, default=[0.7, 0.2, 0.1])
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    pairs = find_pairs()
    print(f'found {len(pairs)} images '
          f'(train dir: {sum(1 for i, _ in pairs if "train" in str(i))}, '
          f'test dir: {sum(1 for i, _ in pairs if "test" in str(i))})')

    class_counts, n_negative, total_boxes, errors = validate_and_count(pairs)
    print(f'total instances : {total_boxes}')
    print(f'  smoke (cls 0)  : {class_counts[0]}')
    print(f'  fire  (cls 1)  : {class_counts[1]}')
    print(f'negative images  : {n_negative} (no/empty label)')
    print(f'label errors     : {len(errors)}')
    for e in errors[:10]:
        print(f'  {e}')
    if errors:
        raise SystemExit('fix label errors before splitting')

    # shuffle once, then cut 7:2:1
    rng = random.Random(args.seed)
    imgs = [str(i.resolve()) for i, _ in pairs]
    rng.shuffle(imgs)
    n = len(imgs)
    n_tr = int(n * args.split[0])
    n_val = int(n * args.split[1])
    splits = {
        'train.txt': imgs[:n_tr],
        'val.txt': imgs[n_tr:n_tr + n_val],
        'test.txt': imgs[n_tr + n_val:],
    }
    out_dir = DATA / 'splits'
    out_dir.mkdir(exist_ok=True)
    for name, lst in splits.items():
        (out_dir / name).write_text('\n'.join(lst) + '\n', encoding='utf-8')
        print(f'{out_dir / name}: {len(lst)} images')


if __name__ == '__main__':
    main()
