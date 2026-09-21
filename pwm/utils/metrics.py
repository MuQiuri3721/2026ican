"""Detection metrics: per-class AP / mAP (COCO-style, 101-point interp)."""
import numpy as np


def box_iou_xyxy(boxes1: np.ndarray, boxes2: np.ndarray) -> np.ndarray:
    """Pairwise IoU between (n,4) and (m,4) xyxy arrays -> (n,m)."""
    x1 = np.maximum(boxes1[:, None, 0], boxes2[None, :, 0])
    y1 = np.maximum(boxes1[:, None, 1], boxes2[None, :, 1])
    x2 = np.minimum(boxes1[:, None, 2], boxes2[None, :, 2])
    y2 = np.minimum(boxes1[:, None, 3], boxes2[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    a1 = (boxes1[:, 2] - boxes1[:, 0]) * (boxes1[:, 3] - boxes1[:, 1])
    a2 = (boxes2[:, 2] - boxes2[:, 0]) * (boxes2[:, 3] - boxes2[:, 1])
    return inter / (a1[:, None] + a2[None, :] - inter + 1e-9)


def match_predictions(pred_boxes, pred_cls, gt_boxes, gt_cls, iou_thr):
    """Greedy score-ordered matching. Returns tp array aligned with preds.

    Callers pass predictions sorted by confidence (descending).
    """
    n, m = len(pred_boxes), len(gt_boxes)
    tp = np.zeros(n, dtype=np.float32)
    if n == 0 or m == 0:
        return tp
    iou = box_iou_xyxy(pred_boxes, gt_boxes)                # (n, m)
    matched_gt = np.zeros(m, dtype=bool)
    for i in range(n):
        iou_i = iou[i].copy()
        iou_i[gt_cls != pred_cls[i]] = -1.0
        j = int(np.argmax(iou_i))
        if iou_i[j] >= iou_thr and not matched_gt[j]:
            tp[i] = 1.0
            matched_gt[j] = True
    return tp


def compute_ap(recall: np.ndarray, precision: np.ndarray) -> float:
    """101-point interpolated AP (COCO style)."""
    r = np.concatenate(([0.0], recall, [1.0]))
    p = np.concatenate(([1.0], precision, [0.0]))
    p = np.maximum.accumulate(p[::-1])[::-1]        # monotone envelope
    points = np.linspace(0, 1, 101)
    ap = 0.0
    for thr in points:
        idx = np.where(r >= thr)[0]
        ap += p[idx[0]] if len(idx) else 0.0
    return ap / 101.0


def ap_per_class(tp, conf, pred_cls, target_cls, iou_thrs=(0.5,)):
    """Aggregate AP over classes and IoU thresholds.

    tp       : (n_preds,) flags for a single IoU threshold, or
               (n_preds, n_thrs) — one tp column per IoU threshold, rows
               aligned with conf/pred_cls (each prediction appears ONCE).
               The flat (n_preds * n_thrs,) concatenation is NOT a valid
               input: it mixes thresholds into one PR curve.
    conf     : (n_preds,)
    pred_cls : (n_preds,)
    target_cls: (n_total_gt,)
    Returns {class_id: {iou: ap}}, plus mean metrics helpers.
    """
    results = {}
    tp_all = np.asarray(tp)
    two_d = tp_all.ndim == 2
    unique_classes = np.unique(np.concatenate([pred_cls, target_cls])) \
        if len(pred_cls) or len(target_cls) else np.array([], dtype=int)
    for c in unique_classes:
        sel_p = pred_cls == c
        sel_t = target_cls == c
        n_gt = int(sel_t.sum())
        # sort this class's predictions by confidence desc
        order = np.argsort(-conf[sel_p])
        tp_c = tp_all[sel_p][order]
        n_pred = len(tp_c)
        if n_gt == 0:
            results[int(c)] = {thr: float('nan') for thr in iou_thrs}
            continue
        if n_pred == 0:
            results[int(c)] = {thr: 0.0 for thr in iou_thrs}
            continue
        if two_d:
            tpc = tp_c.cumsum(0)
            fpc = (1 - tp_c).cumsum(0)
        else:
            tpc = tp_c.cumsum()
            fpc = (1 - tp_c).cumsum()
        recall = tpc / n_gt
        precision = tpc / (tpc + fpc)
        results[int(c)] = {}
        for i, thr in enumerate(iou_thrs):
            r = recall[:, i] if two_d else recall
            p = precision[:, i] if two_d else precision
            results[int(c)][thr] = compute_ap(r, p)
    return results


def evaluate_detections(all_tp, all_conf, all_pred_cls, all_target_cls,
                        iou_thrs=(0.5,)):
    """mAP over classes and IoU thresholds. Inputs are flat arrays that
    concatenate per-image, per-IoU-threshold results.

    For multiple IoU thresholds, callers should build tp with shape
    (n_preds, n_thrs) and pass each column along with the same conf/cls.
    Returns (per_class_ap: dict, mAP50: float, mAP5095: float or None).
    """
    per_class = ap_per_class(all_tp, all_conf, all_pred_cls, all_target_cls,
                             iou_thrs=iou_thrs)
    mAP50 = np.nanmean([v[iou_thrs[0]] for v in per_class.values()]) \
        if per_class else 0.0
    if len(iou_thrs) > 1:
        mAP5095 = np.nanmean([np.mean(list(v.values())) for v in per_class.values()]) \
            if per_class else 0.0
    else:
        mAP5095 = None
    return per_class, float(mAP50), (None if mAP5095 is None else float(mAP5095))
