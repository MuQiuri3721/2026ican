# 真实火场测试图（YOLO real 链路验证用）

来源：D-Fire 数据集（CC BY 4.0）test 划分正样本，含火焰+烟雾多目标。
用途：`python e2e/sweep.py` 之外的 real 链路人工验证——上传后应显示
「YOLO 真实检测 · pwm-yolo · local-yolo-service」，面积由真实检测框换算
（如 AoF07718 → 过火面积 543.08 m²、5 框）。
注意：e2e/*.jpg 根目录的 fixed 测试图是合成简笔画，YOLO 检不出属正确行为。
