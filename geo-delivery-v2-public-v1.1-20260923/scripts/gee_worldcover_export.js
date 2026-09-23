/**
 * 火巡智策：ESA WorldCover 2021 v200 地表覆盖数据（GEE Code Editor）
 *
 * 南京市范围产物：
 * 1) 完整地表分类 COG GeoTIFF；2) 类别 10 派生的树木覆盖 COG GeoTIFF；
 * 3) 元数据 CSV；4) 各地表类别统计 CSV。
 *
 * 范围沿用 SRTM 脚本：南京市行政边界向外缓冲 5 km。
 * 南京边界来源为天地图；准确下载 URL、获取日期、服务版本和许可条款
 * 仍须按实际下载记录补入交付清单，不能由本脚本推断。
 * 下载时间与本地文件 SHA256 无法由 GEE 获取，导出时标为待补。
 */

var CONFIG = {
  exportFolder: 'fire_patrol_worldcover_v2',
  outputScaleM: 10,
  bufferM: 5000,
  noData: 255,
  maxPixels: 1e13,
  regions: [
    {
      id: 'nanjing',
      nameZh: '南京市',
      processingCrs: 'EPSG:32650',
      aoiAsset: 'projects/my-project-260421-494009/assets/nanjing_boundary_wgs84',
      boundarySourceProvider: '国家地理信息公共服务平台（天地图）',
      boundarySourceUrl: 'PENDING_EXACT_DOWNLOAD_URL',
      boundarySourceVersion: 'PENDING_SOURCE_VERSION_OR_UPDATE_DATE',
      boundaryDownloadedAt: 'PENDING_BOUNDARY_DOWNLOAD_DATE',
      boundaryLicenseOrTerms: 'PENDING_EXACT_TERMS_URL'
    }
  ]
};

var SOURCE = {
  assetId: 'ESA/WorldCover/v200',
  datasetId: 'ESA_WorldCover_2021_v200',
  sourceVersion: '2021 v200',
  sourceUrl:
    'https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200',
  provider: 'ESA WorldCover Consortium',
  sensorOrModel: 'Land-cover product derived from Sentinel-1 and Sentinel-2 data',
  sourceBand: 'Map',
  sourceBandUnit: 'land-cover class code',
  nativeResolution: '10 m',
  temporalCoverage: '2021-01-01/2022-01-01',
  licenseOrTerms: 'CC BY 4.0'
};

var CLASS_INFO = [
  {value: 10, name: 'Tree cover', color: '006400'},
  {value: 20, name: 'Shrubland', color: 'ffbb22'},
  {value: 30, name: 'Grassland', color: 'ffff4c'},
  {value: 40, name: 'Cropland', color: 'f096ff'},
  {value: 50, name: 'Built-up', color: 'fa0000'},
  {value: 60, name: 'Bare / sparse vegetation', color: 'b4b4b4'},
  {value: 70, name: 'Snow and ice', color: 'f0f0f0'},
  {value: 80, name: 'Permanent water bodies', color: '0064c8'},
  {value: 90, name: 'Herbaceous wetland', color: '0096a0'},
  {value: 95, name: 'Mangroves', color: '00cf75'},
  {value: 100, name: 'Moss and lichen', color: 'fae6a0'}
];

var runTimestampUtc = new Date().toISOString();
var worldCover = ee.ImageCollection(SOURCE.assetId)
  .first()
  .select(SOURCE.sourceBand)
  .rename('landcover')
  .toUint8();

function assertConfigured(region) {
  if (region.aoiAsset.indexOf('REPLACE_WITH_YOUR_PROJECT') !== -1) {
    throw new Error(
      '请先把 ' + region.nameZh + ' 的 aoiAsset 替换为已确认的 GEE 面资产 ID。'
    );
  }
}

function baseMetadata(region, productName, bandName, fileName, valueMeaning) {
  return {
    schema_version: 'fire-patrol-geo-metadata-v1',
    dataset_id: region.id + '_worldcover_2021_v200_' + productName,
    region_id: region.id,
    region_name_zh: region.nameZh,
    product_name: productName,
    output_file: fileName + '.tif',
    band_name: bandName,
    value_meaning: valueMeaning,
    pixel_type: 'UInt8',
    source_dataset_id: SOURCE.datasetId,
    source_asset_id: SOURCE.assetId,
    source_version: SOURCE.sourceVersion,
    source_url: SOURCE.sourceUrl,
    provider: SOURCE.provider,
    sensor_or_model: SOURCE.sensorOrModel,
    source_band: SOURCE.sourceBand,
    source_band_unit: SOURCE.sourceBandUnit,
    native_resolution: SOURCE.nativeResolution,
    temporal_coverage: SOURCE.temporalCoverage,
    data_currency_type: 'static',
    static_data_date: '2021',
    license_or_terms: SOURCE.licenseOrTerms,
    aoi_asset_id: region.aoiAsset,
    boundary_source_provider: region.boundarySourceProvider,
    boundary_source_url: region.boundarySourceUrl,
    boundary_source_version: region.boundarySourceVersion,
    boundary_downloaded_at: region.boundaryDownloadedAt,
    boundary_license_or_terms: region.boundaryLicenseOrTerms,
    spatial_scope: 'Nanjing municipal boundary plus 5000 m buffer',
    buffer_m: CONFIG.bufferM,
    output_crs: region.processingCrs,
    output_resolution_m: CONFIG.outputScaleM,
    nodata: CONFIG.noData,
    export_format: 'GeoTIFF (cloud optimized)',
    export_requested_at_utc: runTimestampUtc,
    downloaded_at: 'PENDING_AFTER_DOWNLOAD',
    sha256: 'PENDING_AFTER_DOWNLOAD',
    qa_status: 'PENDING',
    processing_software: 'Google Earth Engine',
    processing_method:
      'ESA WorldCover 2021 v200 clipped to Nanjing municipal boundary plus 5 km; ' +
      'exported to EPSG:32650 at 10 m; categorical values use nearest-neighbor sampling',
    interpretation_limit:
      'Class 10 and the derived tree-cover mask are remote-sensing tree cover, ' +
      'not an official forest management boundary or forest-resource survey'
  };
}

function exportRegion(region) {
  assertConfigured(region);

  // 【彻底绕过 GEE 单位推断 BUG 的极简处理法】
  
  // 1. 获取最原始的多边形（此时它是默认的 WGS84）
  var rawGeom = ee.FeatureCollection(region.aoiAsset).geometry();
  
  // 2. 先强行转换到目标米制坐标系，容差为 1。
  // 此时 aoiUtm 的“身份”就已经变成了米制（EPSG:32650）
  var aoiUtm = rawGeom.transform(region.processingCrs, 1);
  
  // 3. 在米制状态下融合可能存在的交叉多边形
  var dissolvedUtm = aoiUtm.dissolve(1);
  
  // 4. 执行缓冲！
  // 核心注意：只传 distance (5000) 和 maxError (1)。
  // 绝不能传第三个参数 proj，这样 GEE 引擎就会百分之百使用 dissolvedUtm 当前的“米”作为单位，完美兼容。
  var bufferedUtm = dissolvedUtm.buffer(CONFIG.bufferM, 1);

  // 保留全部 11 个官方分类值；Earth Engine 对分类数据默认使用最近邻取样。
  var landcover = worldCover.clip(bufferedUtm).rename('landcover').toUint8();

  // 项目派生层：1=WorldCover 类别 10，0=其他有效类别，255=NoData。
  var treeCover = worldCover
    .eq(10)
    .updateMask(worldCover.mask())
    .clip(bufferedUtm)
    .rename('tree_cover')
    .toUint8();

  var crsTag = region.processingCrs.toLowerCase().replace(':', '');
  var prefix = region.id + '_worldcover_2021_v200_10m_' + crsTag;
  var landcoverName = prefix + '_landcover';
  var treeCoverName = prefix + '_tree_cover';

  var landcoverMeta = baseMetadata(
    region,
    'landcover',
    'landcover',
    landcoverName,
    'Official WorldCover codes: 10,20,30,40,50,60,70,80,90,95,100'
  );
  var treeCoverMeta = baseMetadata(
    region,
    'tree_cover',
    'tree_cover',
    treeCoverName,
    'Derived mask: 1=source class 10; 0=other valid classes; 255=NoData'
  );
  treeCoverMeta.processing_method =
    'Derived from ESA WorldCover 2021 v200 with source class 10 mapped to 1, ' +
    'all other valid source classes mapped to 0; clipped and exported to EPSG:32650 at 10 m';

  landcover = landcover.set(landcoverMeta);
  treeCover = treeCover.set(treeCoverMeta);

  function exportRaster(image, description, fileName) {
    Export.image.toDrive({
      image: image.unmask({value: CONFIG.noData, sameFootprint: false}),
      description: description,
      folder: CONFIG.exportFolder,
      fileNamePrefix: fileName,
      region: bufferedUtm,
      crs: region.processingCrs,
      scale: CONFIG.outputScaleM,
      maxPixels: CONFIG.maxPixels,
      fileFormat: 'GeoTIFF',
      formatOptions: {
        cloudOptimized: true,
        noData: CONFIG.noData
      }
    });
  }

  exportRaster(
    landcover,
    region.id + '_WORLDCOVER_LANDCOVER',
    landcoverName
  );
  exportRaster(
    treeCover,
    region.id + '_WORLDCOVER_TREE_COVER',
    treeCoverName
  );

  var metadataTable = ee.FeatureCollection([
    ee.Feature(null, landcoverMeta),
    ee.Feature(null, treeCoverMeta)
  ]);
  Export.table.toDrive({
    collection: metadataTable,
    description: region.id + '_WORLDCOVER_METADATA',
    folder: CONFIG.exportFolder,
    fileNamePrefix: region.id + '_worldcover_2021_v200_metadata',
    fileFormat: 'CSV'
  });

  // 每个官方类别一行，便于核查分类值、像元数、面积和比例。
  var histogramResult = ee.Dictionary(
    landcover.reduceRegion({
      reducer: ee.Reducer.frequencyHistogram(),
      geometry: bufferedUtm,
      crs: region.processingCrs,
      scale: CONFIG.outputScaleM,
      maxPixels: CONFIG.maxPixels,
      tileScale: 4
    }).get('landcover')
  );

  var validPixelCount = ee.Number(
    histogramResult.values().reduce(ee.Reducer.sum())
  );
  var classStatistics = ee.FeatureCollection(CLASS_INFO.map(function (item) {
    var pixelCount = ee.Number(
      histogramResult.get(ee.Number(item.value).format(), 0)
    );
    return ee.Feature(null, {
      region_id: region.id,
      region_name_zh: region.nameZh,
      class_value: item.value,
      class_name: item.name,
      pixel_count: pixelCount,
      area_m2: pixelCount.multiply(CONFIG.outputScaleM * CONFIG.outputScaleM),
      valid_area_percent: ee.Algorithms.If(
        validPixelCount.gt(0),
        pixelCount.divide(validPixelCount).multiply(100),
        null
      ),
      source_dataset_id: SOURCE.datasetId,
      output_crs: region.processingCrs,
      output_resolution_m: CONFIG.outputScaleM,
      valid_pixel_count_all_classes: validPixelCount,
      export_requested_at_utc: runTimestampUtc
    });
  }));

  Export.table.toDrive({
    collection: classStatistics,
    description: region.id + '_WORLDCOVER_STATISTICS',
    folder: CONFIG.exportFolder,
    fileNamePrefix: region.id + '_worldcover_2021_v200_statistics',
    fileFormat: 'CSV'
  });

  var indexedClasses = landcover.remap(
    CLASS_INFO.map(function (item) { return item.value; }),
    CLASS_INFO.map(function (item, index) { return index; })
  );
  Map.addLayer(
    indexedClasses,
    {
      min: 0,
      max: CLASS_INFO.length - 1,
      palette: CLASS_INFO.map(function (item) { return item.color; })
    },
    region.nameZh + ' WorldCover 2021 v200',
    true
  );
  Map.addLayer(
    treeCover.selfMask(),
    {min: 1, max: 1, palette: ['006400']},
    region.nameZh + ' 树木覆盖（类别 10）',
    false
  );
  
  // 地图展示时，转回 WGS84（同样只传误差 1）
  var aoiForMap = dissolvedUtm.transform('EPSG:4326', 1);
  var bufferForMap = bufferedUtm.transform('EPSG:4326', 1);

  Map.addLayer(
    ee.FeatureCollection([
      ee.Feature(aoiForMap, {boundary_type: 'confirmed_aoi'}),
      ee.Feature(bufferForMap, {boundary_type: 'delivery_extent_aoi_plus_5km'})
    ]).style({color: '00ffff', fillColor: '00000000', width: 2}),
    {},
    region.nameZh + ' AOI 与 5 km 边界',
    true
  );

  print(region.nameZh + ' metadata', metadataTable);
  print(region.nameZh + ' class statistics', classStatistics);
  
  // 提取其最简单的外接边界框并转换，返回给 centerObject，从根源上杜绝复杂面渲染问题
  return bufferedUtm.bounds(1).transform('EPSG:4326', 1);
}

var exportExtentFeatures = [];
CONFIG.regions.forEach(function (region) {
  exportExtentFeatures.push(ee.Feature(exportRegion(region)));
});

// 安全缩放
Map.centerObject(ee.FeatureCollection(exportExtentFeatures), 8);
print('已建立 4 个任务：地表分类、树木覆盖、元数据、分类统计。');
print('请在 Tasks 面板逐项检查并点击 Run。');