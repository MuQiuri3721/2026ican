"""PWM-Net evaluation on the test split: mAP@50, mAP@50:95, P, R, FPS.

Usage:
    python eval.py                          # runs/<name>/weights/best.pth
    python eval.py --weights runs/pwmnet/weights/best.pth
    python eval.py --conf 0.25              # deploy-style P/R (default 0.001 for mAP)
"""
import argparse
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from datasets.fire_dataset import FireDataset, collate_fn
from models.pwm_net import PWMNet
from utils.metrics import match_predictions, evaluate_detections
from utils.postprocess import per_class_nms

ROOT = Path(__file__).resolve().parent
CLASSES = ('smoke', 'fire')   # 与 datasets.fire_dataset.CLASSES 保持一致
IOU_THRS = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)


@torch.no_grad()
def run_eval(model, loader, device, conf_thres=0.001, nms_iou=0.45,
             max_det=300):
    """Returns (metrics dict, per-image wall times in seconds)."""
    model.eval()
    tp_l, conf_l, pcls_l, tcls_l = [], [], [], []
    t_all, t_img = [], []
    for imgs, targets, _ in loader:
        imgs = imgs.to(device)
        torch.cuda.synchronize() if device.type == 'cuda' else None
        t0 = time.time()
        preds = model(imgs)
        dets = model.decode(preds, conf_thres=conf_thres, max_det=max_det)
        det_list = [per_class_nms(d, nms_iou, max_det=max_det).cpu().numpy()
                    for d in dets]
        if device.type == 'cuda':
            torch.cuda.synchronize()
        t_all.append(time.time() - t0)
        t_img.extend([len(imgs)] * 1)

        for det, tgt in zip(det_list, targets):
            gt = tgt.numpy()
            gt_boxes = gt[:, 1:5] if len(gt) else np.zeros((0, 4))
            gt_cls = gt[:, 0].astype(int) if len(gt) else np.zeros(0, int)
            tcls_l.extend(gt_cls.tolist())
            if len(det) == 0:
                continue
            order = np.argsort(-det[:, 5])
            det = det[order]
            tp_img = np.stack(
                [match_predictions(det[:, :4], det[:, 4].astype(int),
                                   gt_boxes, gt_cls, thr) for thr in IOU_THRS],
                axis=1)                                    # (n_det, n_thrs)
            tp_l.append(tp_img)
            conf_l.append(det[:, 5])
            pcls_l.append(det[:, 4].astype(int))

    n_img = sum(t_img)
    fps = n_img / max(sum(t_all), 1e-9)
    per_class, mAP50, mAP5095 = evaluate_detections(
        np.concatenate(tp_l) if tp_l else np.zeros((0, len(IOU_THRS))),
        np.concatenate(conf_l) if conf_l else np.zeros(0),
        np.concatenate(pcls_l) if pcls_l else np.zeros(0),
        np.array(tcls_l, dtype=int), iou_thrs=IOU_THRS)

    # precision / recall at IoU 0.5, reported at the max-F1 operating point
    tp50 = np.concatenate([t[:, 0] for t in tp_l]) \
        if tp_l else np.zeros(0)
    conf50 = np.concatenate(conf_l) \
        if conf_l else np.zeros(0)
    order = np.argsort(-conf50)
    tp_sorted = tp50[order]
    n_gt = len(tcls_l) // len(IOU_THRS)
    tp_cum, fp_cum = tp_sorted.cumsum(), (1 - tp_sorted).cumsum()
    p_curve = tp_cum / np.maximum(tp_cum + fp_cum, 1e-9)
    r_curve = tp_cum / max(n_gt, 1)
    f1 = 2 * p_curve * r_curve / np.maximum(p_curve + r_curve, 1e-9)
    best = int(np.argmax(f1)) if len(f1) else 0

    return {
        'mAP50': mAP50, 'mAP5095': mAP5095, 'per_class': per_class,
        'precision': float(p_curve[best]) if len(p_curve) else 0.0,
        'recall': float(r_curve[best]) if len(r_curve) else 0.0,
        'fps': float(fps),
        'n_img': n_img, 'conf_at_p': float(conf50[order][best]) if len(conf50) else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--weights', default='runs/pwmnet/weights/best.pth')
    ap.add_argument('--split', default='test')
    ap.add_argument('--batch-size', type=int, default=8)
    ap.add_argument('--conf', type=float, default=0.001,
                    help='0.001 for mAP; use ~0.25 for deploy P/R')
    ap.add_argument('--nms-iou', type=float, default=0.45)
    ap.add_argument('--device', default='auto')
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--subset', type=int, default=None)
    args = ap.parse_args()

    device = torch.device('cuda' if (args.device == 'auto' and torch.cuda.is_available())
                          else (args.device if args.device != 'auto' else 'cpu'))
    ckpt = torch.load(args.weights, map_location=device)
    model = PWMNet(num_classes=2).to(device)
    model.load_state_dict(ckpt.get('model', ckpt))
    print(f'weights: {args.weights} (epoch {ckpt.get("epoch", "?")}, '
          f'val mAP50 {ckpt.get("mAP50", "?")}), device: {device}')

    ds = FireDataset(ROOT / 'data' / 'splits' / f'{args.split}.txt', augment=False)
    if args.subset:
        ds.items = ds.items[:args.subset]
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False,
                        num_workers=args.workers, collate_fn=collate_fn)
    print(f'{args.split}: {len(ds)} images')

    m = run_eval(model, loader, device, conf_thres=args.conf, nms_iou=args.nms_iou)
    print(f'\n=== {args.split} results (conf={args.conf}) ===')
    print(f'mAP@50      : {m["mAP50"]:.4f}')
    print(f'mAP@50:95   : {m["mAP5095"]:.4f}')
    print(f'Precision   : {m["precision"]:.4f} (at conf>={m["conf_at_p"]:.3f})')
    print(f'Recall      : {m["recall"]:.4f}')
    print(f'FPS         : {m["fps"]:.1f} (batch={args.batch_size}, {device})')
    for c, aps in sorted(m['per_class'].items()):
        name = CLASSES[c] if c < len(CLASSES) else f'cls{c}'
        print(f'  {name:<6} AP@50={aps[0.5]:.4f}  '
              f'AP@50:95={np.nanmean(list(aps.values())):.4f}')


if __name__ == '__main__':
    main()
