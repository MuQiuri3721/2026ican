# PWM-Net — 无人机影像森林火灾检测网络(火焰 + 烟雾)

轻量检测网络(5.06M 参数),架构:PartialNet 主干 + WTConv 频域增强 + M2S 多尺度注意力,
anchor-free 解耦检测头。输入 640×640,输出火焰/烟雾两类检测框。

## 环境要求

- Python ≥ 3.9,PyTorch ≥ 2.0(CUDA / CPU 均可)
- numpy、opencv-python、torchvision(仅用其 `ops.nms`)
- **无需** timm / easydict / PyWavelets(已内置本地实现)

## 数据格式

YOLO 格式,目录结构:

```
data/
├── train/images/   *.jpg          # 图片
├── train/labels/   *.txt          # 标签:每行 "cls x_center y_center w h"(归一化)
├── test/images/
└── test/labels/
```

类别:0 = smoke,1 = fire（与本项目 data/dfire_yolo 一致；D-Fire 官方 README 为 0=fire/1=smoke，方向相反，换官方原版标签时需同步换回）。标签坐标轻微越界会自动裁剪,负样本(无目标图)允许无标签文件。

`python datasets/check_dataset.py` 可校验标签、统计类别、按比例生成训练/验证/测试划分
(默认 7:2:1,`--split` / `--seed` 可调),输出到 `data/splits/{train,val,test}.txt`。

数据集来源:https://github.com/gaiasd/DFireDataset

## 代码结构

```
models/
  partialnet_backbone.py  PartialNet 主干(t0 变体,输出 S8/S16/S32 三尺度特征)
  partialnet_irpe.py      iRPE 相对位置编码(PartialNet 依赖)
  wtconv.py               WTConv2d(Haar 小波频域卷积,零外部依赖)
  m2s.py                  M2S 多尺度注意力(盒式滤波三谱带 + GAP/GMP 门控 + 三尺度聚合)
  pwm_net.py              整网组装 + decode + NMS
datasets/
  check_dataset.py        数据校验 / 统计 / 划分工具
  fire_dataset.py         Dataset(letterbox + mosaic + 翻转 + 亮度抖动)
utils/
  metrics.py              IoU / 贪心匹配 / AP / mAP@50 / mAP@50:95
  postprocess.py          逐类 NMS(torchvision C++ 实现)
train.py / eval.py / inference.py   训练 / 评估 / 推理三入口
```

## 脚本用法

三个入口的参数均可用 `-h` 查看(`python train.py -h`),要点:

- **train.py**:损失 `0.5·BCE + 7.5·CIoU`,默认 AdamW(lr 1e-3, wd 5e-4, 余弦退火),
  可选 SGD;`--batch-size / --epochs / --lr / --optim / --workers / --val-interval /
  --subset / --pretrained(续训)` 等;权重存 `runs/<name>/weights/{best,last}.pth`,
  日志 `runs/<name>/log.txt`
- **eval.py**:测试集 mAP@50、mAP@50:95、Precision、Recall(max-F1 工作点)、FPS;
  `--weights / --split / --conf / --nms-iou`
- **inference.py**:图片/目录推理,框画在原图坐标(letterbox 逆变换),支持非 ASCII 路径;
  `--source / --weights / --conf / --out`

## 实现要点

- 前向:PartialNet-t0 主干 → WTConv 作用于 C5 → FPN+PAN(C2f 融合)→ M2S ×3 → 解耦头
  (每尺度一个 3×3 隐层 + 1×1 cls/回归分支,ltrb 线性回归,中心点标签分配)
- 数值:损失在 fp32 计算(CUDA 上 forward 可用 bf16 autocast,head 输出已转 fp32);
  CIoU 外接框对四角取 min/max(容忍倒置框,防发散)
- 推理:conf 过滤 → top-1000 截断 → 逐类 NMS(IoU 0.45,上限 300 框)
