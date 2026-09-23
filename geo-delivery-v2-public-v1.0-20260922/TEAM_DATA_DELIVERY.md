# 团队数据包与平台接入

本项目采用“公开代码仓库 + 团队内部数据包”的双层交付方式。

## 三份清单

| 清单 | 用途 | 是否公开 |
|---|---|---|
| `manifest_full.json` | 本地完整归档，包含生产原始数据、正式成果、处理脚本、元数据和 QA | 否 |
| `manifest_platform.json` | 平台运行数据包，包含正式 `data/`、元数据和 QA，不包含原始 PBF/GPKG 和处理中间文件 | 团队内部 |
| `manifest_public.json` | GitHub 公开仓库实际可见文件的清单 | 是 |

根目录原有的 `manifest.json` 继续作为本地完整数据集汇总清单，供现有流程兼容使用。公开仓库以 `manifest_public.json` 为准。

## 推荐的团队共享目录

```text
geo-delivery-v2-data/
└─ v1.0-20260922/
   ├─ data/
   ├─ metadata/
   ├─ qa/
   ├─ README.md
   ├─ THIRD_PARTY_DATA.md
   └─ manifest_platform.json
```

该数据包可以存放在团队网盘、NAS、实验室服务器或受控共享目录中。不要把包含天地图行政区划矢量的完整团队数据包公开发布。

## 团队成员使用流程

1. 从公开 GitHub 仓库取得代码、数据结构和说明文件。
2. 从团队受控位置取得与代码版本对应的 `v1.0-20260922` 平台数据包。
3. 将平台配置中的 `DATA_ROOT` 指向数据包内的 `data/` 目录。
4. 使用 `manifest_platform.json` 校验文件是否完整、大小和 SHA256 是否一致。
5. 平台读取本地完整版 `data/overview/areas.geojson`；公开展示或对外分发时改用 `data/overview/areas_public.geojson`。

## 平台需要与不需要的内容

平台运行通常需要：

- `data/nanjing/osm/roads.geojson` 和 `road_nodes.geojson`；
- SRTM DEM、坡度、坡向；
- WorldCover和江苏林木覆盖概览；
- 水体、水源和设施候选；
- 当前、24小时预报和72小时回放天气；
- 本地完整区域索引；
- `metadata/`、`qa/` 和 `manifest_platform.json`。

平台运行通常不需要：

- `raw/osm/` 下的江苏PBF、GPKG和压缩包；
- GEE导出或本地重建脚本；
- `planning_regions/raw/` 和 `planning_regions/rebuilt/`；
- Python缓存和临时文件。

## 更新规则

代码变化但数据未变化时，只更新GitHub仓库。正式数据变化时，重新运行：

```text
python scripts/build_root_manifest.py
python scripts/build_distribution_manifests.py
```

随后发布新的团队数据包版本，并同时更新GitHub中的 `manifest_public.json`。不得用新代码搭配未核验的旧数据包，也不得在没有重新计算哈希的情况下手工修改清单。
