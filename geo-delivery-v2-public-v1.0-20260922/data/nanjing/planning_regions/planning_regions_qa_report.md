# 4个规划展示区边界 QA 报告

- QA状态：**PASS**
- 检查时间（UTC）：2026-09-21T14:55:27.741993+00:00
- 成果坐标系：EPSG:4326
- 用途限制：仅用于规划展示和区域索引，不是法定边界或执行调度区。

## 区域统计

| region_id | 名称 | 外轮廓面积（km²） | 核心面积（km²） | 核心覆盖率 | 边界类型 |
|---|---:|---:|---:|---:|---|
| planning_ningzhen_east | 宁镇丘陵东段 | 1279.289 | 1217.541 | 95.17% | project_defined_overview_local_rebuild |
| planning_taihu_hills | 环太湖丘陵 | 1653.002 | 1437.033 | 86.93% | project_defined_overview_local_rebuild |
| planning_yili | 宜溧山地 | 1038.025 | 993.796 | 95.74% | project_defined_overview_local_rebuild |
| planning_yuntai | 云台山 | 196.859 | 187.454 | 95.22% | project_defined_overview_local_rebuild |

## 自动检查

- ✅ 区域数量和 region_id 完整
- ✅ 必填来源与用途限制字段完整
- ✅ 几何非空且有效
- ✅ 成果位于江苏省界内
- ✅ 四个规划展示区之间无显著重叠
- ✅ 林地—丘陵核心层位于对应规划外轮廓内
- ✅ 所有区域均标记为非官方、仅规划展示

## 仍需人工确认

- 云台山派生范围与连云港市政府公布的保护界线图视觉位置是否一致；
- 宁镇丘陵东段是否覆盖目标山体而未明显纳入平原；
- 宜溧山地是否覆盖宜兴南部与溧阳南部连续山地；
- 环太湖丘陵是否排除了宜溧片区，且未将太湖水体纳入。
