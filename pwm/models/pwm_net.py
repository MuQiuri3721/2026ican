"""PWM-Net — PartialNet + WTConv + M2S detector for UAV forest-fire detection.

Overall pipeline (PWM-Net paper Sec. 3, Fig. 1):
    input (B,3,640,640)
      -> PartialNetBackbone (t0)          C3/C4/C5 @ S8/16/32  (64/128/256)
      -> neck: C5 frequency-enhanced by WTConv2d (user spec), then a
         YOLO-style FPN top-down + PAN bottom-up; every fused output
         (P3/P4/P5) is frequency-enhanced by WTConv2d again, placed after
         cross-level aggregation as the paper specifies
      -> M2S attention before each detection head (P3/P4/P5)
      -> simple decoupled conv heads: per scale, nc class logits + 4 ltrb
         box offsets (anchor-free, FCOS-style linear regression)

Head note: the paper keeps the YOLOv11n head (with DFL); this reproduction
follows the project instruction of a simple conv head — BCE + CIoU losses
are applied in train.py.
"""
from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F

try:
    from .partialnet_backbone import PartialNetBackbone
    from .wtconv import WTConv2d
    from .m2s import M2S
except ImportError:
    from partialnet_backbone import PartialNetBackbone
    from wtconv import WTConv2d
    from m2s import M2S


def autopad(k, p=None):
    return p if p is not None else k // 2


class ConvBnAct(nn.Module):
    """Standard Conv-BN-SiLU block."""

    def __init__(self, c1, c2, k=1, s=1, p=None, act=True):
        super().__init__()
        self.conv = nn.Conv2d(c1, c2, k, s, autopad(k, p), bias=False)
        self.bn = nn.BatchNorm2d(c2)
        self.act = nn.SiLU() if act else nn.Identity()

    def forward(self, x):
        return self.act(self.bn(self.conv(x)))


class Bottleneck(nn.Module):
    """3x3 -> 3x3 residual bottleneck."""

    def __init__(self, c1, c2, shortcut=True):
        super().__init__()
        self.cv1 = ConvBnAct(c1, c2, 3)
        self.cv2 = ConvBnAct(c2, c2, 3)
        self.add = shortcut and c1 == c2

    def forward(self, x):
        return x + self.cv2(self.cv1(x)) if self.add else self.cv2(self.cv1(x))


class C2f(nn.Module):
    """YOLO-style fusion block: split, bottleneck chain, concat, 1x1."""

    def __init__(self, c1, c2, n=1, shortcut=False):
        super().__init__()
        self.c = c2 // 2
        self.cv1 = ConvBnAct(c1, 2 * self.c, 1)
        self.cv2 = ConvBnAct((2 + n) * self.c, c2, 1)
        self.m = nn.Sequential(*(Bottleneck(self.c, self.c, shortcut) for _ in range(n)))

    def forward(self, x):
        y = list(self.cv1(x).chunk(2, 1))
        y.extend(m(y[-1]) for m in self.m)
        return self.cv2(torch.cat(y, 1))


class DetectHead(nn.Module):
    """Simple decoupled head: one 3x3 hidden conv, then cls / reg 1x1."""

    def __init__(self, ch, nc, stride):
        super().__init__()
        self.stride = stride
        self.nc = nc
        hid = max(ch // 2, 32)
        self.conv = ConvBnAct(ch, hid, 3)
        self.cls = nn.Conv2d(hid, nc, 1)
        self.reg = nn.Conv2d(hid, 4, 1)

    def forward(self, x):
        h = self.conv(x)
        return self.cls(h), self.reg(h)


class PWMNet(nn.Module):
    """PWM-Net detector.

    Args:
        num_classes: fire and smoke -> 2
        backbone_variant: PartialNet size (default 't0', nano scale)
        wt_levels / wt_kernel: WTConv configuration (Haar db1, as WTConv paper)
        neck_depth: bottlenecks per C2f fusion block
    """

    strides = (8, 16, 32)

    def __init__(self,
                 num_classes: int = 2,
                 backbone_variant: str = 't0',
                 wt_levels: int = 2,
                 wt_kernel: int = 5,
                 neck_depth: int = 2):
        super().__init__()
        self.nc = num_classes

        # ---- P: PartialNet backbone ----------------------------------------
        self.backbone = PartialNetBackbone(backbone_variant, use_spatial_attn=True)
        c3, c4, c5 = self.backbone.out_channels        # t0: 64 / 128 / 256

        # ---- W: WTConv on C5 (user spec) + after each neck aggregation -----
        self.wt_c5 = WTConv2d(c5, c5, kernel_size=wt_kernel, wt_levels=wt_levels)

        # top-down (FPN)
        self.td_proj5 = ConvBnAct(c5, c4, 1)
        self.td_up5 = nn.Upsample(scale_factor=2, mode='nearest')
        self.td_fuse4 = C2f(c4 + c4, c4, n=neck_depth)

        self.td_proj4 = ConvBnAct(c4, c3, 1)
        self.td_up4 = nn.Upsample(scale_factor=2, mode='nearest')
        self.td_fuse3 = C2f(c3 + c3, c3, n=neck_depth)

        # bottom-up (PAN) — fuses with the WTConv-enhanced C5 (256ch), which
        # feeds both the top-down and bottom-up paths (YOLO-style)
        self.bu_down3 = ConvBnAct(c3, c4, 3, s=2)
        self.bu_fuse4 = C2f(c4 + c4, c4, n=neck_depth)

        self.bu_down4 = ConvBnAct(c4, c5, 3, s=2)
        self.bu_fuse5 = C2f(c5 + c5, c5, n=neck_depth)

        # WTConv after cross-level aggregation (paper placement)
        self.wt_p3 = WTConv2d(c3, c3, kernel_size=wt_kernel, wt_levels=wt_levels)
        self.wt_p4 = WTConv2d(c4, c4, kernel_size=wt_kernel, wt_levels=wt_levels)
        self.wt_p5 = WTConv2d(c5, c5, kernel_size=wt_kernel, wt_levels=wt_levels)

        # ---- M: M2S before each detection head ------------------------------
        self.m2s = nn.ModuleList(M2S(c) for c in (c3, c4, c5))

        # ---- detection heads -------------------------------------------------
        self.heads = nn.ModuleList(
            DetectHead(c, num_classes, s) for c, s in zip((c3, c4, c5), self.strides))

    def forward(self, x: torch.Tensor):
        """Returns dict with per-scale lists: 'cls' (B,nc,H,W), 'box' (B,4,H,W)."""
        # backbone
        c3, c4, c5 = self.backbone(x)
        stage = {'C3': c3, 'C4': c4, 'C5': c5}

        # C5 frequency enhancement (user spec)
        c5w = self.wt_c5(c5)
        stage['C5_wt'] = c5w

        # top-down path
        p5_td = self.td_proj5(c5w)
        p4_td = self.td_fuse4(torch.cat([self.td_up5(p5_td), c4], dim=1))
        p3_td = self.td_fuse3(torch.cat([self.td_up4(self.td_proj4(p4_td)), c3], dim=1))

        # bottom-up path
        p4 = self.bu_fuse4(torch.cat([self.bu_down3(p3_td), p4_td], dim=1))
        p5 = self.bu_fuse5(torch.cat([self.bu_down4(p4), c5w], dim=1))
        p3 = p3_td

        # WTConv after cross-level aggregation (paper placement)
        feats = [self.wt_p3(p3), self.wt_p4(p4), self.wt_p5(p5)]
        stage['P3_wt'], stage['P4_wt'], stage['P5_wt'] = feats

        # M2S + heads
        cls_out, box_out = [], []
        for i, (m2s, head) in enumerate(zip(self.m2s, self.heads)):
            y = m2s(feats[i])
            stage[f'P{i + 3}_m2s'] = y
            cls_map, box_map = head(y)
            cls_out.append(cls_map)
            box_out.append(box_map)

        return {'cls': cls_out, 'box': box_out, 'stage': stage}

    @torch.no_grad()
    def decode(self, preds, conf_thres=0.25, max_det=1000):
        """Decode raw head outputs to xyxy boxes (pixel coords, input scale).

        Returns list (per image) of tensors [n, 6] = x1, y1, x2, y2, cls, conf.
        Candidates beyond max_det (highest confidence kept) are dropped before
        NMS to bound its cost at low conf thresholds.
        """
        device = preds['cls'][0].device
        results = []
        B = preds['cls'][0].shape[0]
        all_boxes, all_scores, all_labels = [], [], []

        for cls_map, box_map, stride in zip(preds['cls'], preds['box'], self.strides):
            B_, nc, H, W = cls_map.shape
            scores = torch.sigmoid(cls_map)                       # (B,nc,H,W)
            ltrb = box_map                                        # linear, stride units

            ys, xs = torch.meshgrid(
                torch.arange(H, device=device, dtype=torch.float32),
                torch.arange(W, device=device, dtype=torch.float32),
                indexing='ij')
            cx = (xs + 0.5) * stride
            cy = (ys + 0.5) * stride

            x1 = cx[None] - ltrb[:, 0] * stride
            y1 = cy[None] - ltrb[:, 1] * stride
            x2 = cx[None] + ltrb[:, 2] * stride
            y2 = cy[None] + ltrb[:, 3] * stride
            boxes = torch.stack([x1, y1, x2, y2], dim=-1)         # (B,H,W,4)

            conf, label = scores.max(dim=1)                       # (B,H,W)
            all_boxes.append(boxes.reshape(B, -1, 4))
            all_scores.append(conf.reshape(B, -1))
            all_labels.append(label.reshape(B, -1))

        boxes = torch.cat(all_boxes, dim=1)
        scores = torch.cat(all_scores, dim=1)
        labels = torch.cat(all_labels, dim=1)

        for i in range(B):
            mask = scores[i] > conf_thres
            b, l, s = boxes[i][mask], labels[i][mask], scores[i][mask]
            if max_det and len(s) > max_det:
                idx = s.topk(max_det).indices
                b, l, s = b[idx], l[idx], s[idx]
            results.append(torch.cat(
                [b, l[:, None].float(), s[:, None]], dim=1))
        return results


def nms(boxes_xyxy, scores, iou_thres=0.45):
    """Pure-torch NMS on (n,4) boxes and (n,) scores; returns kept indices."""
    x1, y1, x2, y2 = boxes_xyxy[:, 0], boxes_xyxy[:, 1], boxes_xyxy[:, 2], boxes_xyxy[:, 3]
    areas = (x2 - x1).clamp(0) * (y2 - y1).clamp(0)
    order = scores.argsort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0].item()
        keep.append(i)
        if order.numel() == 1:
            break
        rest = order[1:]
        xx1 = torch.maximum(x1[i], x1[rest])
        yy1 = torch.maximum(y1[i], y1[rest])
        xx2 = torch.minimum(x2[i], x2[rest])
        yy2 = torch.minimum(y2[i], y2[rest])
        inter = (xx2 - xx1).clamp(0) * (yy2 - yy1).clamp(0)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thres]
    return torch.tensor(keep, dtype=torch.long, device=boxes_xyxy.device)


if __name__ == '__main__':
    torch.manual_seed(0)
    model = PWMNet(num_classes=2)
    n_params = sum(p.numel() for p in model.parameters())

    def count(mod):
        return sum(p.numel() for p in mod.parameters()) / 1e6

    x = torch.randn(2, 3, 640, 640)
    model.eval()
    with torch.no_grad():
        preds = model(x)

    print(f'total params: {n_params / 1e6:.2f}M   (paper target 7.8M)')
    print(f'  backbone  : {count(model.backbone):.2f}M')
    print(f'  wtconv    : {(count(model.wt_c5) + count(model.wt_p3) + count(model.wt_p4) + count(model.wt_p5)):.3f}M')
    print(f'  m2s       : {count(model.m2s):.3f}M')

    print('\nstage shapes:')
    for k, v in preds['stage'].items():
        print(f'  {k:8s} {tuple(v.shape)}')

    print('\nhead outputs:')
    for i, (c, b) in enumerate(zip(preds['cls'], preds['box'])):
        print(f'  P{i + 3}: cls {tuple(c.shape)}  box {tuple(b.shape)}')

    dets = model.decode(preds, conf_thres=0.01)
    print(f'\ndecode OK: {len(dets)} images, first image detections: {dets[0].shape[0]}')

    model.train()
    preds_t = model(x)
    loss = sum(c.sum() + b.sum() for c, b in zip(preds_t['cls'], preds_t['box']))
    loss.backward()
    nan_grads = [n for n, p in model.named_parameters()
                 if p.requires_grad and p.grad is not None
                 and not torch.isfinite(p.grad).all()]
    no_grad = [n for n, p in model.named_parameters()
               if p.requires_grad and p.grad is None]
    # norm0 (stride-4 stage output) is intentionally unused: S8/16/32 only
    expected_unused = {'backbone.net.norm0.weight', 'backbone.net.norm0.bias'}
    print(f'backward OK: no NaN/Inf grads = {not nan_grads}; '
          f'unused params = {set(no_grad) == expected_unused} ({no_grad})')
