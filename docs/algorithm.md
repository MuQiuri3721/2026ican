# 算法说明

当前 MVP 使用可解释的规则模型。风险分数为火焰面积、烟雾面积、风速和增长率归一化值的加权和：

```text
R = αa + βs + γw + δg
```

资源需求使用：

```text
M = A_fire × q_base × k_level × k_env × k_safe
```

闭环监测使用：

```text
A_next = max(0, A_t + G_t - F_t)
```

其中自然增长量由当前面积、增长率、风速和时间决定，灭火减少量由本轮灭火资源乘以演示效率系数决定。所有参数在 `configs/simulation.json` 中维护，不能视为真实消防标准。
