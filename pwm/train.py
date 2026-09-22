"""PWM-Net training script (D-Fire, 2 classes: fire / smoke).

Loss      : L = 0.5 * BCE(cls) + 7.5 * CIoU(box)     (paper Sec. 3.4 weights,
            DFL omitted — simple head per project instructions)
Assigner  : anchor-free, each GT is assigned to the cell containing its center
            on every level whose stride is <= max(gt_w, gt_h)
Optimizer : AdamW lr=1e-3 (project spec; --optim sgd matches the paper's
            SGD 0.01/momentum 0.937), cosine annealing
Val       : mAP@50 and mAP@50:95 each epoch; best.pth saved by mAP@50

Smoke test: python train.py --subset 100 --val-subset 50 --epochs 1
Full run  : python train.py --epochs 300 --batch-size 16
"""
import argparse
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from datasets.fire_dataset import FireDataset, collate_fn
from models.pwm_net import PWMNet
from utils.metrics import match_predictions, evaluate_detections
from utils.postprocess import per_class_nms

ROOT = Path(__file__).resolve().parent


def autocast_ctx(device: torch.device):
    """bf16 autocast on CUDA (no GradScaler needed), disabled on CPU."""
    if device.type == 'cuda':
        return torch.autocast(device_type='cuda', dtype=torch.bfloat16)
    return torch.autocast(device_type='cpu', enabled=False)


def to_float(preds):
    """Cast head outputs to fp32 (loss/decode run outside autocast)."""
    return {'cls': [t.float() for t in preds['cls']],
            'box': [t.float() for t in preds['box']],
            'stage': preds['stage']}


# ---------------------------------------------------------------------------
# Loss
# ---------------------------------------------------------------------------
def ciou_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """CIoU loss between aligned xyxy boxes, both (n, 4)."""
    eps = 1e-7
    # 规范化倒置预测框（x2<x1 / y2<y1 交换回正；min/max 可导，梯度正常流动）。
    # bug#4 根因（同基准训练实测：mAP 恒 0.0099、box loss 为负）：负宽高进入 v 项的
    # atan 使 v/alpha·v 无上界，损失整体无下界——优化器沿退化方向"学习"。
    # GT 侧规范化为幂等操作（本就 x1<x2）。
    px1 = torch.minimum(pred[:, 0], pred[:, 2]); px2 = torch.maximum(pred[:, 0], pred[:, 2])
    py1 = torch.minimum(pred[:, 1], pred[:, 3]); py2 = torch.maximum(pred[:, 1], pred[:, 3])
    tx1 = torch.minimum(target[:, 0], target[:, 2]); tx2 = torch.maximum(target[:, 0], target[:, 2])
    ty1 = torch.minimum(target[:, 1], target[:, 3]); ty2 = torch.maximum(target[:, 1], target[:, 3])

    # intersection / union
    ix1 = torch.maximum(px1, tx1); iy1 = torch.maximum(py1, ty1)
    ix2 = torch.minimum(px2, tx2); iy2 = torch.minimum(py2, ty2)
    inter = (ix2 - ix1).clamp(0) * (iy2 - iy1).clamp(0)
    a_p = (px2 - px1).clamp(min=0) * (py2 - py1).clamp(min=0)
    a_t = (tx2 - tx1).clamp(min=0) * (ty2 - ty1).clamp(min=0)
    union = a_p + a_t - inter + eps
    iou = inter / union

    # smallest enclosing box diagonal（规范化后两框中心必然在盒内，rho2/c2 ≤ 1 有保证）
    cx1 = torch.minimum(px1, tx1); cy1 = torch.minimum(py1, ty1)
    cx2 = torch.maximum(px2, tx2); cy2 = torch.maximum(py2, ty2)
    c2 = ((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2 + eps).clamp(min=1e-4)

    # center-point distance
    rho2 = ((px1 + px2) - (tx1 + tx2)) ** 2 / 4 + \
           ((py1 + py2) - (ty1 + ty2)) ** 2 / 4

    # aspect-ratio consistency（规范化后宽高非负 → atan 有界 → v ≤ 4，不再无界）
    v = (4 / math.pi ** 2) * (
        torch.atan((px2 - px1) / (py2 - py1 + eps)) -
        torch.atan((tx2 - tx1) / (ty2 - ty1 + eps))
    ) ** 2
    alpha = v / (1 - iou + v + eps)
    # 下界保底：即便数值边缘情况也绝不给优化器"负损失"的退化方向
    return (1.0 - iou - rho2 / c2 - alpha * v).clamp(min=0)


class DetectionLoss(nn.Module):
    def __init__(self, model: PWMNet, num_classes: int = 2,
                 cls_weight: float = 0.5, box_weight: float = 7.5):
        super().__init__()
        self.nc = num_classes
        self.strides = model.strides
        self.cls_weight = cls_weight
        self.box_weight = box_weight
        # bug#5（cls 塌缩）：正格子占比 ~0.05%，裸 BCE 均值下"全压背景"是稳定局部
        # 最优——22 epochs cls sigmoid max 仅 0.12、decode conf 全灭（实测）。
        # 改逐 batch 动态 pos_weight（负/正比，上限 500）让正格子梯度浮出水面。
        self.pos_weight_cap = 500.0

    def forward(self, preds, targets):
        """preds: model output dict; targets: list of (n_i, 5) [cls,x1,y1,x2,y2]."""
        device = preds['cls'][0].device
        B = preds['cls'][0].shape[0]

        cls_loss = torch.zeros((), device=device)
        box_loss = torch.zeros((), device=device)
        pred_xyxy_all, tgt_xyxy_all = [], []
        n_pos = 0

        for lv, (cls_map, box_map) in enumerate(zip(preds['cls'], preds['box'])):
            s = self.strides[lv]
            _, _, H, W = cls_map.shape
            cls_tgt = torch.zeros_like(cls_map)
            box_tgt = torch.zeros(B, 4, H, W, device=device)

            for b in range(B):
                t = targets[b]
                if len(t) == 0:
                    continue
                # size filter: object must span at least one cell on this level
                spans = torch.maximum(t[:, 3] - t[:, 1], t[:, 4] - t[:, 2])
                sel = spans >= s
                t = t[sel]
                if len(t) == 0:
                    continue
                cx = ((t[:, 1] + t[:, 3]) / 2 / s).long().clamp(0, W - 1)
                cy = ((t[:, 2] + t[:, 4]) / 2 / s).long().clamp(0, H - 1)
                cls_tgt[b, t[:, 0].long(), cy, cx] = 1.0
                box_tgt[b, :, cy, cx] = t[:, 1:5].T

            pos_n = cls_tgt.sum()
            neg_n = cls_tgt.numel() - pos_n
            pw = torch.tensor(min(neg_n / max(pos_n, 1.0), self.pos_weight_cap),
                              device=cls_map.device)
            cls_loss = cls_loss + torch.nn.functional.binary_cross_entropy_with_logits(
                cls_map, cls_tgt, pos_weight=pw)

            # decode predicted ltrb -> xyxy at cells where a target exists
            pos = cls_tgt.sum(1) > 0                               # (B,H,W)
            if pos.any():
                n_pos += int(pos.sum())
                ys, xs = torch.meshgrid(
                    torch.arange(H, device=device, dtype=torch.float32),
                    torch.arange(W, device=device, dtype=torch.float32),
                    indexing='ij')
                cxg = (xs + 0.5) * s
                cyg = (ys + 0.5) * s
                ltrb = box_map.permute(0, 2, 3, 1)[pos]            # (p,4)
                x1 = cxg[None].expand_as(pos)[pos].unsqueeze(1) - ltrb[:, 0:1] * s
                y1 = cyg.unsqueeze(0).expand_as(pos)[pos].unsqueeze(1) - ltrb[:, 1:2] * s
                x2 = cxg[None].expand_as(pos)[pos].unsqueeze(1) + ltrb[:, 2:3] * s
                y2 = cyg.unsqueeze(0).expand_as(pos)[pos].unsqueeze(1) + ltrb[:, 3:4] * s
                pred_xyxy = torch.cat([x1, y1, x2, y2], dim=1)
                tgt_xyxy = box_tgt.permute(0, 2, 3, 1)[pos]
                pred_xyxy_all.append(pred_xyxy)
                tgt_xyxy_all.append(tgt_xyxy)

        if pred_xyxy_all:
            box_loss = ciou_loss(torch.cat(pred_xyxy_all), torch.cat(tgt_xyxy_all)).mean()

        loss = self.cls_weight * cls_loss + self.box_weight * box_loss
        return loss, {'cls': float(cls_loss.detach()),
                      'box': float(box_loss.detach()), 'n_pos': n_pos}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@torch.no_grad()
def evaluate(model, loader, device, conf_thres=0.001, nms_iou=0.45,
             iou_thrs=(0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)):
    model.eval()
    tp_l, conf_l, pcls_l, tcls_l = [], [], [], []
    t0, n_img = time.time(), 0
    for imgs, targets, _ in loader:
        imgs = imgs.to(device)
        with autocast_ctx(device):
            preds = model(imgs)
        preds = to_float(preds)
        dets = model.decode(preds, conf_thres=conf_thres)
        for det, tgt in zip(dets, targets):
            det = per_class_nms(det.to(device), nms_iou).cpu().numpy()
            gt = tgt.numpy()
            gt_boxes = gt[:, 1:5] if len(gt) else np.zeros((0, 4))
            gt_cls = gt[:, 0].astype(int) if len(gt) else np.zeros(0, int)
            n_img += 1
            # GT classes counted once per image; per-threshold tp flags are
            # stacked as (n_det, n_thrs) so ap_per_class gets one row per
            # detection (a flat per-threshold concatenation would mix all
            # thresholds into a single PR curve)
            tcls_l.extend(gt_cls.tolist())
            if len(det) == 0:
                continue
            order = np.argsort(-det[:, 5])
            det = det[order]
            tp_img = np.stack(
                [match_predictions(det[:, :4], det[:, 4].astype(int),
                                   gt_boxes, gt_cls, thr) for thr in iou_thrs],
                axis=1)
            tp_l.append(tp_img)
            conf_l.append(det[:, 5])
            pcls_l.append(det[:, 4].astype(int))
    per_class, mAP50, mAP5095 = evaluate_detections(
        np.concatenate(tp_l) if tp_l else np.zeros(0),
        np.concatenate(conf_l) if conf_l else np.zeros(0),
        np.concatenate(pcls_l) if pcls_l else np.zeros(0),
        np.array(tcls_l, dtype=int), iou_thrs=iou_thrs)
    dt = time.time() - t0
    model.train()
    return {'mAP50': mAP50, 'mAP5095': mAP5095, 'per_class': per_class,
            'n_img': n_img, 'sec': dt}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train_one_epoch(model, loader, loss_fn, optimizer, device, epoch, log_every=20):
    model.train()
    total, agg = 0.0, {'cls': 0.0, 'box': 0.0}
    t0 = time.time()
    for it, (imgs, targets, _) in enumerate(loader):
        imgs = imgs.to(device)
        targets = [t.to(device) for t in targets]
        with autocast_ctx(device):
            preds = model(imgs)
        # compute the loss in fp32 — CIoU's division goes unstable in bf16
        preds = to_float(preds)
        loss, parts = loss_fn(preds, targets)
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        optimizer.step()
        total += float(loss.detach())
        agg['cls'] += parts['cls']
        agg['box'] += parts['box']
        if (it + 1) % log_every == 0:
            n = it + 1
            print(f'  epoch {epoch} it {n}/{len(loader)} '
                  f'loss={total / n:.3f} (cls={agg["cls"] / n:.3f} '
                  f'box={agg["box"] / n:.3f}) {n / (time.time() - t0):.2f} it/s',
                  flush=True)
    return total / max(len(loader), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=300)
    ap.add_argument('--batch-size', type=int, default=16)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--weight-decay', type=float, default=5e-4)
    ap.add_argument('--optim', choices=['adamw', 'sgd'], default='adamw')
    ap.add_argument('--device', default='auto')
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--pretrained', type=str, default=None,
                    help='checkpoint path to start from')
    ap.add_argument('--subset', type=int, default=None,
                    help='limit train images (smoke test)')
    ap.add_argument('--val-subset', type=int, default=None,
                    help='limit val images (smoke test)')
    ap.add_argument('--name', default='pwmnet')
    ap.add_argument('--val-interval', type=int, default=1,
                    help='validate every N epochs (saves wall-clock)')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(max(4, torch.get_num_threads()))

    device = torch.device('cuda' if (args.device == 'auto' and torch.cuda.is_available())
                          else (args.device if args.device != 'auto' else 'cpu'))
    print(f'device: {device}')

    # data
    split_dir = ROOT / 'data' / 'splits'
    train_ds = FireDataset(split_dir / 'train.txt', augment=True)
    val_ds = FireDataset(split_dir / 'val.txt', augment=False)
    if args.subset:
        train_ds.items = train_ds.items[:args.subset]
    if args.val_subset:
        val_ds.items = val_ds.items[:args.val_subset]
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.workers, collate_fn=collate_fn,
                              drop_last=True, persistent_workers=args.workers > 0)
    val_loader = DataLoader(val_ds, batch_size=8, shuffle=False,
                            num_workers=args.workers, collate_fn=collate_fn)
    print(f'train: {len(train_ds)} images, val: {len(val_ds)} images')

    # model
    model = PWMNet(num_classes=2).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'PWM-Net params: {n_params / 1e6:.2f}M')
    start_epoch = 0
    if args.pretrained:
        ckpt = torch.load(args.pretrained, map_location=device)
        state = ckpt.get('model', ckpt)
        model.load_state_dict(state, strict=False)
        print(f'loaded pretrained: {args.pretrained}')

    if args.optim == 'adamw':
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                      weight_decay=args.weight_decay)
    else:
        optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=0.937)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=args.lr * 0.01)
    loss_fn = DetectionLoss(model, num_classes=2)

    out_dir = ROOT / 'runs' / args.name
    (out_dir / 'weights').mkdir(parents=True, exist_ok=True)
    log_path = out_dir / 'log.txt'
    best_map = -1.0

    for epoch in range(start_epoch, args.epochs):
        lr = optimizer.param_groups[0]['lr']
        print(f'--- epoch {epoch + 1}/{args.epochs} lr={lr:.5f}', flush=True)
        tr_loss = train_one_epoch(model, train_loader, loss_fn, optimizer,
                                  device, epoch + 1)
        do_val = ((epoch + 1) % args.val_interval == 0) or \
                 ((epoch + 1) == args.epochs)
        if do_val:
            metrics = evaluate(model, val_loader, device)
            line = (f'epoch {epoch + 1}: train_loss={tr_loss:.4f} '
                    f'mAP50={metrics["mAP50"]:.4f} '
                    f'mAP5095={metrics["mAP5095"]:.4f} '
                    f'({metrics["n_img"]} imgs, {metrics["sec"]:.0f}s)')
        else:
            metrics = None
            line = f'epoch {epoch + 1}: train_loss={tr_loss:.4f} (no val)'
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

        torch.save({'model': model.state_dict(), 'epoch': epoch + 1,
                    'mAP50': metrics['mAP50'] if metrics else -1.0},
                   out_dir / 'weights' / 'last.pth')
        if metrics and metrics['mAP50'] > best_map:
            best_map = metrics['mAP50']
            torch.save({'model': model.state_dict(), 'epoch': epoch + 1,
                        'mAP50': metrics['mAP50']},
                       out_dir / 'weights' / 'best.pth')
            print(f'  saved best.pth (mAP50={best_map:.4f})', flush=True)
        scheduler.step()

    print(f'done. best mAP50 = {best_map:.4f}')


if __name__ == '__main__':
    main()
