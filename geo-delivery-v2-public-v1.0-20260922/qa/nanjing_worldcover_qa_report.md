# 南京 WorldCover 2021 v200 质量检查

核查范围：南京市行政边界及其外扩 5 km。边界来自天地图行政区划下载入口，原始坐标参考记录为 CGCS2000；WorldCover 数据来自 ESA WorldCover Consortium，并通过 Google Earth Engine 获取和处理。

## 自动检查结果

| 检查项 | 结果 |
|---|---|
| CRS | PASS |
| pixel size | PASS |
| data type | PASS |
| NoData | PASS |
| land-cover class values | PASS |
| tree-cover values | PASS |
| same grid/shape/transform | PASS |
| tree-mask derivation | PASS |
| NoData masks | PASS |
| COG layout | PASS |
| internal overviews | PASS |
| SHA256 calculated | PASS |

- 栅格尺寸：9328 × 16277。
- 栅格范围：[623440.0, 3451670.0, 716720.0, 3614440.0]（EPSG:32650，单位 m）。
- 有效地表分类像元：94,471,674。
- WorldCover 类别 10（Tree cover）像元：29,029,492，占有效分类像元 30.728250%。
- 树木覆盖派生不一致像元：0。
- NoData 掩膜不一致像元：0。
- 统计表已按最终交付 TIFF 重算，`pixel_count` 为严格整数；面积按 10 m × 10 m 完整像元计算。

Tree cover 百分比仅表示 WorldCover 遥感分类中类别 10 的像元比例，不等同于南京市官方森林覆盖率、森林资源调查结果或林区管理边界。

## 视觉检查

- `worldcover_nanjing_overview.png`：南京全域分类概览。
- `worldcover_boundary_overlay.png`：南京边界、5 km 交付范围与分类栅格叠加。
- `worldcover_tree_cover_detail.png`：树木覆盖、建设用地和永久水体混合区域局部检查。
- 视觉复核状态：**PASS**。

视觉检查用于发现整体平移、边界错位、大片异常空值和明显分类渲染问题，不代表逐像元地面真实性核验。

## 文件校验值

- `nanjing_worldcover_2021_v200_10m_epsg32650_landcover.tif`: `B118CC683251E589ECB9EDC1E20D057A304FCD97A95B66B4DB8484FD1C32F55C`
- `nanjing_worldcover_2021_v200_10m_epsg32650_tree_cover.tif`: `B821575A660810D1B2350B6EE699986D8BE02AE1AF091577D449ABE740E1CB00`
- `nanjing_worldcover_2021_v200_metadata.csv`: `0179A82EDABF6D2077C2DA41B7A21B34E97C10FBAB43640E25E9F7BD4C9A4D08`
- `nanjing_worldcover_2021_v200_statistics.csv`: `4F0EB9F8427DA5609DB7DEB2FEE342B64EDF481A2232F0DE677569687617203B`

## 来源与许可

- ESA WorldCover 2021 v200：`ESA/WorldCover/v200`，10 m，`Map` 波段，11类，CC BY 4.0。
- Earth Engine目录：https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200
- ESA产品页：https://esa-worldcover.org/en/data-access
- DOI：https://doi.org/10.5281/zenodo.7254221
- 南京边界下载入口：https://cloudcenter.tianditu.gov.cn/administrativeDivision
- 天地图未在本次下载记录中提供独立数据版本号，记录为 `not_provided_by_source`；使用时保留天地图来源署名并遵守平台条款。

## 结论

WorldCover 自动检查全部通过。最终结论：**PASS**。
