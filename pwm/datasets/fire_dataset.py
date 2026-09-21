"""FireDataset — YOLO-format D-Fire dataset with letterbox + augmentations.

Each item returns:
    img    : float32 tensor (3, 640, 640), range [0, 1], RGB
    targets: float32 tensor (n, 5) = [cls, x1, y1, x2, y2] in 640-px coords
             (empty tensor (0, 5) for negative images)
    path   : str

Augmentations (train only): 4-image mosaic (p=0.5), horizontal flip (p=0.5),
light brightness/contrast jitter. Validation/test use plain letterbox.
Boxes slightly outside the image (D-Fire quirk) are clamped to bounds.
"""
import random
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

IMG_SIZE = 640
# 类别口径以实际训练数据 data/dfire_yolo 为准（0=smoke, 1=fire，2026-09-21 画框目检实证，
# 与 dfire.yaml 一致）。注意：D-Fire 官方 README 写的是 0=fire/1=smoke，与本数据镜像相反；
# 若换用官方原版标签训练，需把这里和 inference/eval 的 CLASSES 一并换回。
CLASSES = ('smoke', 'fire')


def letterbox(img, size=IMG_SIZE, color=(114, 114, 114)):
    """Resize keeping aspect ratio, pad to size x size. Returns img, ratio, pad."""
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = round(h * r), round(w * r)
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top, left = (size - nh) // 2, (size - nw) // 2
    out = np.full((size, size, 3), color, dtype=np.uint8)
    out[top:top + nh, left:left + nw] = img
    return out, r, (left, top)


def load_labels(label_path: Path, orig_w, orig_h, r, pad, size=IMG_SIZE):
    """Read YOLO labels -> (n, 5) [cls, x1, y1, x2, y2] in letterboxed px."""
    targets = []
    if label_path is not None and label_path.exists():
        text = label_path.read_text(encoding='utf-8').strip()
        if text:
            for line in text.splitlines():
                p = line.split()
                if len(p) != 5:
                    continue
                cls = int(p[0])
                x, y, w, h = map(float, p[1:])
                # clamp the D-Fire overshoot quirk to image bounds
                x1 = max(0.0, (x - w / 2)) * orig_w
                y1 = max(0.0, (y - h / 2)) * orig_h
                x2 = min(1.0, (x + w / 2)) * orig_w
                y2 = min(1.0, (y + h / 2)) * orig_h
                # to letterboxed pixel coords
                x1, x2 = x1 * r + pad[0], x2 * r + pad[0]
                y1, y2 = y1 * r + pad[1], y2 * r + pad[1]
                x1, x2 = np.clip(x1, 0, size - 1), np.clip(x2, 0, size - 1)
                y1, y2 = np.clip(y1, 0, size - 1), np.clip(y2, 0, size - 1)
                if x2 - x1 < 2 or y2 - y1 < 2:   # degenerate after clipping
                    continue
                targets.append([cls, x1, y1, x2, y2])
    return np.array(targets, dtype=np.float32).reshape(-1, 5)


class FireDataset(Dataset):
    def __init__(self, list_file, img_size=IMG_SIZE, augment=False,
                 mosaic_prob=0.5, flip_prob=0.5, jitter_prob=0.5):
        self.img_size = img_size
        self.augment = augment
        self.mosaic_prob = mosaic_prob
        self.flip_prob = flip_prob
        self.jitter_prob = jitter_prob
        self.items = []  # (img_path, label_path or None)
        for line in Path(list_file).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            img = Path(line)
            # label lookup: swap the last 'images' path component to 'labels'.
            # Works for both layouts —
            #   official D-Fire:  <root>/<split>/images/x.jpg -> <root>/<split>/labels/x.txt
            #   ultralytics:      <root>/images/<split>/x.jpg -> <root>/labels/<split>/x.txt
            parts = list(img.parts)
            lbl = None
            if 'images' in parts:
                i = len(parts) - 1 - parts[::-1].index('images')
                lbl = Path(*parts[:i], 'labels', *parts[i + 1:]).with_suffix('.txt')
            else:  # fallback: sibling labels/ of the image's parent dir
                lbl = img.parent.parent / 'labels' / (img.stem + '.txt')
            self.items.append((img, lbl if lbl.exists() else None))

    def __len__(self):
        return len(self.items)

    # ------------------------------------------------------------------ io
    @staticmethod
    def _imread(path):
        """cv2.imread replacement that supports non-ASCII (Chinese) paths."""
        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f'cannot read image: {path}')
        return img

    def _load(self, idx):
        img_path, lbl_path = self.items[idx]
        img = self._imread(img_path)                 # BGR
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        return img, lbl_path, w, h

    def _basic(self, idx):
        """Letterboxed image + targets (no augmentation)."""
        img, lbl_path, w, h = self._load(idx)
        img, r, pad = letterbox(img, self.img_size)
        targets = load_labels(lbl_path, w, h, r, pad, self.img_size)
        return img, targets

    # ----------------------------------------------------------- augment
    @staticmethod
    def _hflip(img, targets):
        w = img.shape[1]
        if len(targets):
            x1 = w - targets[:, 3]
            x2 = w - targets[:, 1]
            # clamp so edge-touching boxes stay inside [0, w-1]
            targets[:, 1] = np.clip(x1, 0, w - 1)
            targets[:, 3] = np.clip(x2, 0, w - 1)
        return img[:, ::-1, :].copy(), targets

    @staticmethod
    def _jitter(img):
        a = 0.7 + random.random() * 0.6   # brightness/contrast factor
        return np.clip(img.astype(np.float32) * a, 0, 255).astype(np.uint8)

    def _mosaic(self, idx):
        """Classic 4-image mosaic: 2x canvas, random crop to img_size."""
        s = self.img_size
        ids = [idx] + [random.randrange(len(self)) for _ in range(3)]
        imgs, tgts = [], []
        for i in ids:
            im, t = self._basic(i)
            imgs.append(im)
            tgts.append(t)

        canvas = np.full((s * 2, s * 2, 3), 114, dtype=np.uint8)
        cx, cy = random.randint(s // 2, s + s // 2), random.randint(s // 2, s + s // 2)
        merged = []
        # paste 4 quadrants (TL/TR/BL/BR) around the random center; quadrant
        # origins may be negative/overflowing, so paste the intersection only
        for k, (im, t) in enumerate(zip(imgs, tgts)):
            ox = cx - s if k % 2 == 0 else cx
            oy = cy - s if k < 2 else cy
            x1a, y1a = max(ox, 0), max(oy, 0)
            x2a, y2a = min(ox + s, s * 2), min(oy + s, s * 2)
            if x2a <= x1a or y2a <= y1a:
                continue  # fully outside the canvas
            x1b, y1b = x1a - ox, y1a - oy
            x2b, y2b = x1b + (x2a - x1a), y1b + (y2a - y1a)
            canvas[y1a:y2a, x1a:x2a] = im[y1b:y2b, x1b:x2b]
            if len(t):
                t = t.copy()
                t[:, 1] += ox
                t[:, 2] += oy
                t[:, 3] += ox
                t[:, 4] += oy
                # clip boxes to the pasted region
                t[:, 1] = np.clip(t[:, 1], x1a, x2a)
                t[:, 3] = np.clip(t[:, 3], x1a, x2a)
                t[:, 2] = np.clip(t[:, 2], y1a, y2a)
                t[:, 4] = np.clip(t[:, 4], y1a, y2a)
                merged.append(t)
        targets = np.concatenate(merged, 0) if merged else np.zeros((0, 5), np.float32)

        # random crop back to s x s
        x0 = random.randint(max(cx - s, 0), min(cx, s))
        y0 = random.randint(max(cy - s, 0), min(cy, s))
        img = canvas[y0:y0 + s, x0:x0 + s]
        if len(targets):
            targets[:, [1, 3]] -= x0
            targets[:, [2, 4]] -= y0
            targets[:, [1, 3]] = np.clip(targets[:, [1, 3]], 0, s - 1)  # x
            targets[:, [2, 4]] = np.clip(targets[:, [2, 4]], 0, s - 1)  # y
            keep = (targets[:, 3] - targets[:, 1] > 4) & \
                   (targets[:, 4] - targets[:, 2] > 4)
            targets = targets[keep]
        return img, targets

    # ------------------------------------------------------------- forward
    def __getitem__(self, idx):
        if self.augment and random.random() < self.mosaic_prob:
            img, targets = self._mosaic(idx)
        else:
            img, targets = self._basic(idx)
            if self.augment and random.random() < self.jitter_prob:
                img = self._jitter(img)

        if self.augment and random.random() < self.flip_prob:
            img, targets = self._hflip(img, targets)

        img_t = torch.from_numpy(np.ascontiguousarray(img)).permute(2, 0, 1).float() / 255.0
        tgt_t = torch.from_numpy(np.ascontiguousarray(targets))
        return img_t, tgt_t, str(self.items[idx][0])


def collate_fn(batch):
    imgs = torch.stack([b[0] for b in batch])
    return imgs, [b[1] for b in batch], [b[2] for b in batch]


if __name__ == '__main__':
    from torch.utils.data import DataLoader

    split_dir = Path(__file__).resolve().parents[1] / 'data' / 'splits'
    train_ds = FireDataset(split_dir / 'train.txt', augment=True)
    val_ds = FireDataset(split_dir / 'val.txt', augment=False)
    print(f'train: {len(train_ds)} images, val: {len(val_ds)} images')

    loader = DataLoader(train_ds, batch_size=4, shuffle=True, num_workers=0,
                        collate_fn=collate_fn)
    imgs, targets, paths = next(iter(loader))
    print(f'batch imgs : {tuple(imgs.shape)}  range [{imgs.min():.2f}, {imgs.max():.2f}]')
    for t, p in zip(targets, paths):
        clss = t[:, 0].int().tolist() if len(t) else []
        n_fire = clss.count(0)
        n_smoke = clss.count(1)
        print(f'  {Path(p).name}: {len(t)} boxes (fire={n_fire}, smoke={n_smoke}), '
              f'target shape {tuple(t.shape)}')

    # label coordinate sanity
    assert imgs.shape == (4, 3, IMG_SIZE, IMG_SIZE)
    for t in targets:
        if len(t):
            assert t[:, 1:].min() >= 0 and t[:, 1:].max() < IMG_SIZE
            assert (t[:, 3] > t[:, 1]).all() and (t[:, 4] > t[:, 2]).all()
    print('DataLoader OK; all box coords valid')
