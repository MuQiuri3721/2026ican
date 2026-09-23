# 火巡智策 Geo Delivery V2

本目录是火巡智策项目的地理与气象数据交付包，覆盖南京详细数据、江苏省级概览、四个规划展示区、统一元数据和 QA 结果。

当前本地完整交付包的根级 Manifest 状态为 `PASS`。公开 GitHub 版本会主动排除受第三方使用限制的行政区划矢量和超大原始文件，因此“本地完整包”和“公开仓库”包含的文件范围不同。

## 数据模块

| 模块 | 主要内容 | 正式目录 |
|---|---|---|
| 南京 SRTM | DEM、坡度、坡向、统计与固定核查点 | `data/nanjing/srtm/` |
| 南京 WorldCover | ESA WorldCover 2021 v200 地表覆盖 | `data/nanjing/worldcover/` |
| 江苏林木覆盖概览 | 江苏省及13市林木覆盖统计和概览成果 | `data/nanjing/jiangsu_tree_cover_overview/` |
| 南京 OSM | 道路、节点、水体、水源和设施候选 | `data/nanjing/osm/` |
| 南京气象 | 当前、未来24小时预报和过去72小时回放 | `data/nanjing/weather/` |
| 四个规划展示区 | 云台山、宁镇丘陵东段、宜溧山地、环太湖丘陵 | `data/nanjing/planning_regions/` |
| 统一区域索引 | 本地完整索引、公开规划区索引、元数据和 QA | `data/overview/` |
| 数据溯源与质量记录 | 来源、处理链、分发清单、哈希和 QA | `metadata/`、`qa/`、`manifest_*.json` |

## 空间入口

本项目提供两个用途不同的空间入口：

- `data/overview/areas.geojson`：本地完整索引，包含江苏省、13个设区市、南京详细数据区和4个规划展示区。由于其中含有天地图来源的完整行政区划几何，该文件**仅保留在本地完整交付包，不进入公开仓库**。
- `data/overview/areas_public.geojson`：公开仓库入口，只包含4个项目派生规划展示区，不包含天地图行政边界。

四个规划展示区均为项目派生概览范围，不是法定行政区、官方规划边界、保护区边界或可执行调度区域。

## 公开仓库发布规则

天地图行政区划下载界面标注“该数据仅供地图可视化使用”。本项目据此采用以下发布策略：

- 本地项目可将相关边界用于地图可视化、裁剪、范围判断和内部空间处理；
- 公开仓库不上传天地图下载的原始行政区划矢量；
- 公开仓库不上传能够基本还原江苏省、13个设区市或南京完整行政边界的派生矢量；
- 来源元数据、处理脚本、统计结果、项目派生规划区和渲染后的 QA 图片可以公开；
- SRTM、WorldCover、OSM 和 Open-Meteo 成果分别遵守各自数据源的许可与署名要求，不因行政边界限制而自动变成不可发布数据。

详细的第三方数据说明见 `THIRD_PARTY_DATA.md`，天地图边界溯源和发布状态见 `metadata/nanjing_boundary_provenance.json`。

团队内部平台接入不依赖 GitHub 提供大文件。完整使用方式见 `TEAM_DATA_DELIVERY.md`：公开仓库负责代码、规范和轻量成果，平台数据包通过团队网盘、NAS、服务器或受控共享目录交付。

## 分发清单

- `manifest_full.json`：本地完整归档清单，不公开；
- `manifest_platform.json`：团队平台数据包清单，不含生产原始文件；
- `manifest_public.json`：GitHub 公开版清单；
- `manifest.json`：兼容既有流程的本地完整数据集汇总清单。

公开仓库以 `manifest_public.json` 为准。不能使用本地 `manifest.json` 检查 GitHub clone 结果，否则会把按策略排除的文件误报为缺失。

## 公开仓库不会包含的文件

`.gitignore` 已排除以下内容：

- `raw/osm/` 下的江苏 PBF、GPKG 和压缩包；
- 超过 GitHub 普通文件限制的 `roads.geojson` 和 `road_nodes.geojson`；
- 江苏省、13市、南京的天地图来源边界文件；
- 本地完整 `areas.geojson` 和南京边界/5 km 缓冲矢量；
- 本地完整、平台和引用受限文件的子级 Manifest；
- 规划区 `raw/`、`rebuilt/` 中间目录；
- Python 缓存和临时文件。

这些文件在本地完整包中继续保留。公开仓库缺少它们是合规和文件体积控制措施，不代表数据处理任务未完成。

## 目录结构

```text
geo-delivery-v2/
├─ data/
│  ├─ nanjing/
│  │  ├─ srtm/
│  │  ├─ worldcover/
│  │  ├─ jiangsu_tree_cover_overview/
│  │  ├─ osm/
│  │  ├─ weather/
│  │  └─ planning_regions/
│  └─ overview/
├─ metadata/
├─ qa/
├─ raw/                 # 本地原始数据，公开仓库排除
├─ scripts/
├─ manifest.json        # 兼容既有流程的本地汇总清单
├─ manifest_full.json
├─ manifest_platform.json
├─ manifest_public.json
├─ TEAM_DATA_DELIVERY.md
├─ THIRD_PARTY_DATA.md
└─ README.md
```

`raw/` 和 `rebuilt/` 主要用于复现和审计。平台接入应优先读取 `data/` 下的正式成果，并根据公开或本地部署场景选择对应的区域索引。

## 数据质量与可追溯性

根级 `manifest.json` 汇总本地各数据模块；三份 `manifest_*.json` 分别对应完整归档、平台数据包和公开仓库。清单记录文件大小和 SHA256，各模块同时保留相应元数据、QA 报告或可视化检查图。

当前主要 QA 内容包括：

- 栅格 CRS、分辨率、范围、NoData 和像元统计；
- SRTM 10个固定核查点；
- WorldCover 分类、覆盖和边界叠加检查；
- OSM 道路节点引用、几何、水体和设施候选检查；
- 天气时间范围、时区、字段和缺测检查；
- 四个规划区的几何有效性和碎片重建检查；
- 统一区域索引的 ID、层级和空间一致性检查。

`PASS` 表示结构、处理链和既定 QA 检查通过，不表示第三方候选设施已经全部完成现场核验，也不表示项目派生规划区具有官方边界效力。

## 关键数据来源

- NASA/USGS SRTMGL1 v003：高程和地形派生数据；
- ESA WorldCover 2021 v200：地表覆盖和江苏林木覆盖概览；
- OpenStreetMap contributors / Geofabrik：道路、水体和设施候选；
- Open-Meteo：当前、预报和历史回放气象数据；
- 国家地理信息公共服务平台（天地图）：本地地图可视化和空间处理使用的行政区划边界；
- 本项目派生：四个规划展示区和公开规划区索引。

## 复现说明

处理脚本位于 `scripts/`。GEE 脚本中的 Asset ID 是当次项目环境记录，复现者需要替换为自己的 Earth Engine Asset 路径。脚本导出阶段保留的 `qa_status=PENDING` 表示下载后仍需执行本地 QA；本目录正式成果已经完成相应本地检查，最终状态以模块 QA 和根级 `manifest.json` 为准。

公开仓库不提供的 OSM 原始文件应按元数据中记录的来源和日期重新获取，再运行对应处理脚本。未经权利方明确许可，不应通过其他渠道重新上传本项目所排除的天地图行政边界矢量。
