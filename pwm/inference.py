"""PWM-Net inference: detect fire/smoke on an image or a directory of images.

Boxes are drawn on the ORIGINAL image (letterbox coords mapped back).

Usage:
    python inference.py --source path/to/img.jpg
    python inference.py --source path/to/dir --out runs/pred
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
import torch

from datasets.fire_dataset import letterbox
from models.pwm_net import PWMNet
from utils.postprocess import per_class_nms

ROOT = Path(__file__).resolve().parent
CLASSES = ('smoke', 'fire')   # 与 datasets.fire_dataset.CLASSES 保持一致
COLORS = {  # BGR
    0: (160, 160, 60),  # smoke - gray-blue
    1: (0, 69, 255),    # fire  - red
}


def imread(path):
    """cv2.imread replacement that supports non-ASCII (Chinese) paths."""
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f'cannot read image: {path}')
    return img


def imwrite(path, img):
    """cv2.imwrite replacement that supports non-ASCII (Chinese) paths."""
    ext = Path(path).suffix or '.jpg'
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f'cannot encode image: {path}')
    buf.tofile(str(path))


@torch.no_grad()
def detect(model, img_bgr, device, img_size=640, conf_thres=0.25, nms_iou=0.45):
    """Returns (dets [n,6] xyxy in ORIGINAL pixel coords, letterboxed tensor)."""
    h0, w0 = img_bgr.shape[:2]
    img, r, (pad_x, pad_y) = letterbox(img_bgr, img_size)
    x = torch.from_numpy(img).permute(2, 0, 1).float().div(255).unsqueeze(0).to(device)
    preds = model(x)
    det = model.decode(preds, conf_thres=conf_thres)[0]
    det = per_class_nms(det, nms_iou)
    if len(det) == 0:
        return det.cpu().numpy(), img
    det = det.cpu().numpy()
    # letterboxed px -> original px
    det[:, [0, 2]] = (det[:, [0, 2]] - pad_x) / r
    det[:, [1, 3]] = (det[:, [1, 3]] - pad_y) / r
    det[:, [0, 2]] = det[:, [0, 2]].clip(0, w0 - 1)
    det[:, [1, 3]] = det[:, [1, 3]].clip(0, h0 - 1)
    return det, img


def draw(img, dets):
    out = img.copy()
    for x1, y1, x2, y2, cls, conf in dets:
        c = int(cls)
        color = COLORS.get(c, (255, 255, 255))
        x1, y1, x2, y2 = map(int, (x1, y1, x2, y2))
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = f'{CLASSES[c] if c < len(CLASSES) else c} {conf:.2f}'
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        y_text = max(y1 - 4, th + base + 4)
        cv2.rectangle(out, (x1, y_text - th - base - 4), (x1 + tw + 4, y_text), color, -1)
        cv2.putText(out, label, (x1 + 2, y_text - base - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, help='image file or directory')
    ap.add_argument('--weights', default='runs/pwmnet/weights/best.pth')
    ap.add_argument('--out', default=None, help='output dir (default: runs/pred)')
    ap.add_argument('--conf', type=float, default=0.25)
    ap.add_argument('--nms-iou', type=float, default=0.45)
    ap.add_argument('--img-size', type=int, default=640)
    ap.add_argument('--device', default='auto')
    args = ap.parse_args()

    device = torch.device('cuda' if (args.device == 'auto' and torch.cuda.is_available())
                          else (args.device if args.device != 'auto' else 'cpu'))
    ckpt = torch.load(args.weights, map_location=device)
    model = PWMNet(num_classes=2).to(device)
    model.load_state_dict(ckpt.get('model', ckpt))
    model.eval()
    print(f'weights: {args.weights} (epoch {ckpt.get("epoch", "?")}), device: {device}')

    src = Path(args.source)
    exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    files = sorted(p for p in (src.iterdir() if src.is_dir() else [src])
                   if p.suffix.lower() in exts) if (src.is_dir() or src.exists()) else []
    if not files:
        raise SystemExit(f'no images found under: {src}')

    out_dir = Path(args.out) if args.out else ROOT / 'runs' / 'pred'
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f'{len(files)} image(s) -> {out_dir}')

    for p in files:
        img = imread(p)
        dets, _ = detect(model, img, device, args.img_size, args.conf, args.nms_iou)
        n_fire = int((dets[:, 4] == 0).sum()) if len(dets) else 0
        n_smoke = int((dets[:, 4] == 1).sum()) if len(dets) else 0
        vis = draw(img, dets)
        out_path = out_dir / f'{p.stem}_pred{p.suffix}'
        imwrite(out_path, vis)
        print(f'  {p.name}: {len(dets)} box (fire={n_fire}, smoke={n_smoke}) -> {out_path.name}')


if __name__ == '__main__':
    main()
