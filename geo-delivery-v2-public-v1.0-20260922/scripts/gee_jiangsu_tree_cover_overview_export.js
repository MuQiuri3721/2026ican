/**
 * 火巡智策：江苏省林木覆盖概览（Google Earth Engine Code Editor）
 *
 * 对应《火巡智策地理与气象数据任务方案 V2》的省级概览任务：
 * 1. 使用 ESA WorldCover 2021 v200 的 Map 波段；
 * 2. 将类别 10 派生为“遥感树木覆盖”；
 * 3. 以原始 10 m 数据计算江苏省及 13 个设区市的覆盖面积和比例；
 * 4. 生成 100 m 树木覆盖比例概览栅格，不导出全省 10 m 精细栅格。
 *
 * 重要限制：WorldCover 类别 10 是遥感树木覆盖分类，不等于林权边界、
 * 官方森林资源调查结果、树种或可燃物载量。
 *
 * 使用前：
 * - 将 jiangsu_province_boundary_wgs84 上传为 GEE Table Asset；
 * - 将 jiangsu_prefecture_boundaries_wgs84 上传为 GEE Table Asset；
 * - 用上传后得到的完整 Asset ID 替换 CONFIG 中两个占位符；
 * - 市界资产必须保留 name 和 gb 字段。
 */

var CONFIG = {
  exportFolder: 'fire_patrol_jiangsu_overview_v2',

  // 必须替换成自己的 GEE Asset ID。
  provinceAsset:
    'projects/my-project-260421-494009/assets/jiangsu_province_boundary_wgs84',
  prefectureAsset:
    'projects/my-project-260421-494009/assets/jiangsu_prefecture_boundaries_wgs84',

  prefectureNameField: 'name',
  prefectureCodeField: 'gb',

  // 使用 GEE 原生完美支持的 EPSG:3857 避免 UTM 跨带。
  // 由于下文使用了 pixelArea()，面积计算基于地球真实球面，不受 Web Mercator 投影形变的影响。
  analysisCrs: 'EPSG:3857',
  statisticsScaleM: 10,
  overviewScaleM: 100,
  overviewNoData: 255,
  maxPixels: 1e13,
  maxPixelsPerRegion: 2e9,
  tileScale: 8,

  boundarySourceProvider: '国家地理信息公共服务平台（天地图）',
  boundarySourceUrl:
    'https://cloudcenter.tianditu.gov.cn/administrativeDivision',
  boundaryOriginalCrs: 'CGCS2000 / EPSG:4490',
  boundaryDeliveryCrs: 'WGS 84 / OGC:CRS84',
  boundaryDownloadedAt: '2026-09-20',
  boundarySourceVersion: 'not_provided_by_source',
  boundaryLicenseOrTerms: 'not_provided_by_source'
};

var SOURCE = {
  assetId: 'ESA/WorldCover/v200',
  datasetId: 'ESA_WorldCover_2021_v200',
  productName: 'ESA WorldCover 10 m 2021',
  productVersion: 'v200',
  productYear: 2021,
  provider: 'ESA WorldCover Consortium',
  sourceUrl:
    'https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200',
  doi: '10.5281/zenodo.7254221',
  sensorOrModel: 'Sentinel-1 SAR + Sentinel-2 MSI derived land-cover product',
  sourceBand: 'Map',
  nativeResolutionM: 10,
  temporalCoverage: '2021-01-01/2022-01-01',
  licenseOrTerms: 'CC BY 4.0',
  treeClassValue: 10,
  treeClassName: 'Tree cover'
};

var EXPECTED_PREFECTURES = [
  '南京市', '无锡市', '徐州市', '常州市', '苏州市', '南通市', '连云港市',
  '淮安市', '盐城市', '扬州市', '镇江市', '泰州市', '宿迁市'
];

function assertConfigured(assetId, label) {
  if (assetId.indexOf('REPLACE_WITH_YOUR_PROJECT') !== -1) {
    throw new Error('请先替换 ' + label + ' 的 GEE Asset ID。');
  }
}

assertConfigured(CONFIG.provinceAsset, '江苏省界');
assertConfigured(CONFIG.prefectureAsset, '江苏市界');

var runTimestampUtc = new Date().toISOString();
var province = ee.FeatureCollection(CONFIG.provinceAsset);
var prefectures = ee.FeatureCollection(CONFIG.prefectureAsset);

// 强制在米制坐标系 (EPSG:3857) 下进行 dissolve
var provinceGeometry = province.geometry().dissolve(1, CONFIG.analysisCrs);

// 官方目录为 ImageCollection；v200 当前包含 2021 年产品。
var worldCover = ee.ImageCollection(SOURCE.assetId)
  .first()
  .select(SOURCE.sourceBand)
  .rename('landcover')
  .toUint8();

var validMask = worldCover.mask().rename('valid_worldcover');
var treeMask = worldCover
  .eq(SOURCE.treeClassValue)
  .updateMask(validMask)
  .rename('tree_cover')
  .toUint8();

// 这个变量强制执行重投影和重采样，专供后台 Export 导出任务使用。
var exportTreeCoverPercent100m = treeMask
  .toFloat()
  .reduceResolution({
    reducer: ee.Reducer.mean(),
    bestEffort: false,
    maxPixels: 1024
  })
  .reproject({
    crs: CONFIG.analysisCrs,
    scale: CONFIG.overviewScaleM
  })
  .multiply(100)
  .round()
  .toUint8()
  .rename('tree_cover_percent')
  .clip(provinceGeometry);

var overviewFileName =
  'jiangsu_tree_cover_overview_2021_v200_100m_epsg3857';

Export.image.toDrive({
  image: exportTreeCoverPercent100m.unmask({
    value: CONFIG.overviewNoData,
    sameFootprint: false
  }),
  description: 'JIANGSU_TREE_COVER_OVERVIEW_100M',
  folder: CONFIG.exportFolder,
  fileNamePrefix: overviewFileName,
  region: provinceGeometry,
  crs: CONFIG.analysisCrs,
  scale: CONFIG.overviewScaleM,
  maxPixels: CONFIG.maxPixels,
  fileFormat: 'GeoTIFF',
  formatOptions: {
    cloudOptimized: true,
    noData: CONFIG.overviewNoData
  }
});

// 面积统计仍使用原始 10 m 分类。
// ee.Image.pixelArea() 计算的是绝对的球面物理面积，不受投影形变影响。
var areaImage = ee.Image.pixelArea()
  .updateMask(validMask)
  .rename('valid_worldcover_area_m2')
  .addBands(
    ee.Image.pixelArea()
      .updateMask(treeMask)
      .rename('tree_cover_area_m2')
  );

function finalizeStatistics(feature, adminLevel) {
  feature = ee.Feature(feature);
  var validAreaM2 = ee.Number(feature.get('valid_worldcover_area_m2'));
  var treeAreaM2 = ee.Number(feature.get('tree_cover_area_m2'));
  var adminAreaM2 = feature.geometry().area(1);

  var name = ee.Algorithms.If(
    adminLevel === 'province',
    '江苏省',
    feature.get(CONFIG.prefectureNameField)
  );
  var gb = ee.Algorithms.If(
    adminLevel === 'province',
    '156320000',
    feature.get(CONFIG.prefectureCodeField)
  );

  return ee.Feature(null, {
    region_id: gb,
    region_name_zh: name,
    admin_level: adminLevel,
    gb_code: gb,
    admin_area_m2: adminAreaM2,
    admin_area_km2: adminAreaM2.divide(1e6),
    valid_worldcover_area_m2: validAreaM2,
    valid_worldcover_area_km2: validAreaM2.divide(1e6),
    tree_cover_area_m2: treeAreaM2,
    tree_cover_area_km2: treeAreaM2.divide(1e6),
    tree_cover_percent_of_valid: ee.Algorithms.If(
      validAreaM2.gt(0),
      treeAreaM2.divide(validAreaM2).multiply(100),
      null
    ),
    valid_coverage_percent_of_admin: ee.Algorithms.If(
      adminAreaM2.gt(0),
      validAreaM2.divide(adminAreaM2).multiply(100),
      null
    ),
    source_dataset_id: SOURCE.datasetId,
    source_asset_id: SOURCE.assetId,
    source_version: SOURCE.productVersion,
    source_year: SOURCE.productYear,
    source_band: SOURCE.sourceBand,
    tree_class_value: SOURCE.treeClassValue,
    statistics_resolution_m: CONFIG.statisticsScaleM,
    statistics_crs: CONFIG.analysisCrs,
    export_requested_at_utc: runTimestampUtc
  });
}

var prefectureRawStats = areaImage.reduceRegions({
  collection: prefectures,
  reducer: ee.Reducer.sum(),
  scale: CONFIG.statisticsScaleM,
  crs: CONFIG.analysisCrs,
  tileScale: CONFIG.tileScale,
  maxPixelsPerRegion: CONFIG.maxPixelsPerRegion
});

var prefectureStatistics = prefectureRawStats.map(function (feature) {
  return finalizeStatistics(feature, 'prefecture');
});

var provinceSums = areaImage.reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: provinceGeometry,
  scale: CONFIG.statisticsScaleM,
  crs: CONFIG.analysisCrs,
  maxPixels: CONFIG.maxPixels,
  tileScale: CONFIG.tileScale
});

var provinceFeatureForStats = ee.Feature(
  provinceGeometry,
  provinceSums
);
var provinceStatistics = ee.FeatureCollection([
  finalizeStatistics(provinceFeatureForStats, 'province')
]);

var allStatistics = provinceStatistics
  .merge(prefectureStatistics)
  .sort('gb_code');

Export.table.toDrive({
  collection: allStatistics,
  description: 'JIANGSU_TREE_COVER_STATISTICS',
  folder: CONFIG.exportFolder,
  fileNamePrefix:
    'jiangsu_tree_cover_statistics_2021_v200_province_and_prefectures',
  fileFormat: 'CSV',
  selectors: [
    'region_id',
    'region_name_zh',
    'admin_level',
    'gb_code',
    'admin_area_m2',
    'admin_area_km2',
    'valid_worldcover_area_m2',
    'valid_worldcover_area_km2',
    'tree_cover_area_m2',
    'tree_cover_area_km2',
    'tree_cover_percent_of_valid',
    'valid_coverage_percent_of_admin',
    'source_dataset_id',
    'source_asset_id',
    'source_version',
    'source_year',
    'source_band',
    'tree_class_value',
    'statistics_resolution_m',
    'statistics_crs',
    'export_requested_at_utc'
  ]
});

var metadata = ee.FeatureCollection([
  ee.Feature(null, {
    schema_version: 'fire-patrol-geo-metadata-v1',
    dataset_id: 'jiangsu_tree_cover_overview_2021_v200',
    region_id: 'jiangsu',
    region_name_zh: '江苏省',
    product_name: 'tree_cover_percent_overview',
    output_file: overviewFileName + '.tif',
    band_name: 'tree_cover_percent',
    value_meaning:
      '0--100 = percent of valid source area classified as WorldCover class 10; 255 = NoData',
    pixel_type: 'UInt8',
    source_dataset_id: SOURCE.datasetId,
    source_asset_id: SOURCE.assetId,
    source_product_name: SOURCE.productName,
    source_version: SOURCE.productVersion,
    source_year: SOURCE.productYear,
    source_url: SOURCE.sourceUrl,
    source_doi: SOURCE.doi,
    provider: SOURCE.provider,
    source_sensor_or_model: SOURCE.sensorOrModel,
    source_band: SOURCE.sourceBand,
    source_band_unit: 'land-cover class code',
    source_native_resolution_m: SOURCE.nativeResolutionM,
    temporal_coverage: SOURCE.temporalCoverage,
    tree_class_value: SOURCE.treeClassValue,
    tree_class_name: SOURCE.treeClassName,
    license_or_terms: SOURCE.licenseOrTerms,
    province_boundary_asset_id: CONFIG.provinceAsset,
    prefecture_boundary_asset_id: CONFIG.prefectureAsset,
    boundary_source_provider: CONFIG.boundarySourceProvider,
    boundary_source_url: CONFIG.boundarySourceUrl,
    boundary_source_version: CONFIG.boundarySourceVersion,
    boundary_downloaded_at: CONFIG.boundaryDownloadedAt,
    boundary_original_crs: CONFIG.boundaryOriginalCrs,
    boundary_delivery_crs: CONFIG.boundaryDeliveryCrs,
    boundary_license_or_terms: CONFIG.boundaryLicenseOrTerms,
    spatial_scope: 'Jiangsu provincial administrative boundary',
    processing_method:
      'WorldCover class 10 converted to 0/1 at native 10 m; area-weighted mean aggregated to 100 m overview pixels',
    statistics_method:
      'Tree-cover and valid-source areas summed from native-classification mask at 10 m for the province and 13 prefectures',
    output_crs: CONFIG.analysisCrs,
    output_resolution_m: CONFIG.overviewScaleM,
    statistics_resolution_m: CONFIG.statisticsScaleM,
    nodata: CONFIG.overviewNoData,
    export_format: 'GeoTIFF (cloud optimized) + CSV',
    data_currency_type: 'static',
    export_requested_at_utc: runTimestampUtc,
    downloaded_at: 'PENDING_AFTER_DOWNLOAD',
    sha256: 'PENDING_AFTER_DOWNLOAD',
    qa_status: 'PENDING',
    processing_software: 'Google Earth Engine',
    interpretation_limit:
      'Remote-sensing tree cover only; not an official forest boundary, forest-resource survey, tree-species map, or fuel-load estimate'
  })
]);

Export.table.toDrive({
  collection: metadata,
  description: 'JIANGSU_TREE_COVER_METADATA',
  folder: CONFIG.exportFolder,
  fileNamePrefix: 'jiangsu_tree_cover_overview_2021_v200_metadata',
  fileFormat: 'CSV'
});

// 在网页地图上直接展示基于 GEE 影像金字塔的原生 10m 树木覆盖情况（仅视觉预览）。
Map.centerObject(provinceGeometry.transform('EPSG:4326', 1), 7);
Map.addLayer(
  treeMask.selfMask().clip(provinceGeometry),
  {
    min: 1,
    max: 1,
    palette: ['006837']
  },
  '江苏省树木覆盖 10m原生预览 (将导出为100m)',
  true
);

Map.addLayer(
  province.style({color: '111111', fillColor: '00000000', width: 3}),
  {},
  '江苏省界',
  true
);
Map.addLayer(
  prefectures.style({color: 'ffffff', fillColor: '00000000', width: 1}),
  {},
  '13个设区市边界',
  true
);

print('省界要素数（期望 1）', province.size());
print('市界要素数（期望 13）', prefectures.size());
print(
  '市名（应与 EXPECTED_PREFECTURES 一致）',
  prefectures.aggregate_array(CONFIG.prefectureNameField).sort()
);
print('期望市名', ee.List(EXPECTED_PREFECTURES).sort());

// 【修复核心：移除超时的控制台绘图和打印代码，让任务直接进入后台计算】
print('⚠️ 提示：全省 10m 精度的面积统计计算量极大，无法在网页控制台实时预览（会导致超时）。');
print('✅ 请放心，真实的精确统计数据将在后台执行，请到右侧 Tasks 面板点击 "JIANGSU_TREE_COVER_STATISTICS" 任务右侧的 Run 按钮进行导出。');

print('✅ 最终已建立 3 个导出任务：100 m概览栅格、统计CSV、元数据CSV。');
print('💡 请先核对地图、市界数量和市名，再到 Tasks 面板逐项点击 Run。');
