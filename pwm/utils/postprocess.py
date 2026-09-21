"""Post-processing: per-class NMS on decoded detections."""
import torch
from torchvision.ops import nms as tv_nms


def per_class_nms(dets: torch.Tensor, iou_thr: float = 0.45,
                  max_det: int = 300) -> torch.Tensor:
    """dets: (n, 6) = x1, y1, x2, y2, cls, conf -> kept (m, 6), m <= max_det.

    Uses torchvision's compiled NMS on CPU tensors (fast, and works with a
    CPU-only torchvision build regardless of where dets came from).
    """
    if len(dets) == 0:
        return dets
    dets = dets.detach().cpu().float()
    keep_parts = []
    for c in dets[:, 4].unique():
        part = dets[dets[:, 4] == c]
        idx = tv_nms(part[:, :4], part[:, 5], iou_thr)
        keep_parts.append(part[idx])
    out = torch.cat(keep_parts, dim=0)
    if len(out) > max_det:  # keep highest-confidence
        out = out[out[:, 5].argsort(descending=True)][:max_det]
    return out
