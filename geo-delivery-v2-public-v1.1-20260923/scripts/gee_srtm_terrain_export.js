/**
 * 火巡智策：SRTM 高程及地形派生数据（GEE Code Editor）
 *
 * 南京市范围产物：
 * 1) DEM COG GeoTIFF；2) 坡度 COG GeoTIFF；3) 坡向 COG GeoTIFF；
 * 4) AOI/5 km 边界 GeoJSON；5) 元数据 CSV；6) 描述统计 CSV。
 *
 * 必须把 aoiAsset 替换成上传后的南京市行政边界面资产 ID。
 * 下载时间与本地文件 SHA256 无法由 GEE 获取，导出时标为待补。
 */

var CONFIG = {
  exportFolder: 'fire_patrol_srtm_v2',
  outputScaleM: 30,
  bufferM: 5000,
  noData: -9999,
  maxPixels: 1e13,
  regions: [
    {
      id: 'nanjing',
      nameZh: '南京市',
      processingCrs: 'EPSG:32650',
      aoiAsset: 'projects/my-project-260421-494009/assets/nanjing_boundary_wgs84'
    }
  ]
};

var SOURCE = {
  assetId: 'USGS/SRTMGL1_003',
  datasetId: 'NASA_SRTMGL1_003',
  sourceVersion: 'SRTMGL1 v003',
  sourceUrl: 'https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003',
  provider: 'NASA / USGS / JPL-Caltech',
  sensorOrModel: 'Shuttle Radar Topography Mission interferometric radar',
  sourceBand: 'elevation',
  sourceBandUnit: 'm',
  nativeResolution: '1 arc-second (~30 m)',
  nativeCrs: 'EPSG:4326',
  temporalCoverage: '2000-02-11/2000-02-22',
  verticalDatum: 'EGM96 geoid',
  licenseOrTerms: 'NASA Earthdata data-use policy; attribution is recommended'
};

var runTimestampUtc = new Date().toISOString();
var srtm = ee.Image(SOURCE.assetId).select(SOURCE.sourceBand);

function assertConfigured(region) {
  if (region.aoiAsset.indexOf('REPLACE_WITH_YOUR_PROJECT') !== -1) {
    throw new Error(
      '请先把 ' + region.nameZh + ' 的 aoiAsset 替换为已确认的 GEE 面资产 ID。'
    );
  }
}

function baseMetadata(region, productName, bandName, unit, fileName, pixelType) {
  return {
    schema_version: 'fire-patrol-geo-metadata-v1',
    dataset_id: region.id + '_srtmgl1_003_' + productName,
    region_id: region.id,
    region_name_zh: region.nameZh,
    product_name: productName,
    output_file: fileName + '.tif',
    band_name: bandName,
    unit: unit,
    pixel_type: pixelType,
    source_dataset_id: SOURCE.datasetId,
    source_asset_id: SOURCE.assetId,
    source_version: SOURCE.sourceVersion,
    source_url: SOURCE.sourceUrl,
    provider: SOURCE.provider,
    sensor_or_model: SOURCE.sensorOrModel,
    source_band: SOURCE.sourceBand,
    source_band_unit: SOURCE.sourceBandUnit,
    native_resolution: SOURCE.nativeResolution,
    native_crs: SOURCE.nativeCrs,
    temporal_coverage: SOURCE.temporalCoverage,
    data_currency_type: 'static',
    static_data_date: SOURCE.temporalCoverage,
    vertical_datum: SOURCE.verticalDatum,
    license_or_terms: SOURCE.licenseOrTerms,
    aoi_asset_id: region.aoiAsset,
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
      'SRTM elevation reprojected to EPSG:32650 at 30 m with bilinear resampling; ' +
      'slope and aspect derived with ee.Terrain.products; clipped to Nanjing municipal boundary plus 5 km buffer',
    method_note:
      'ee.Terrain.products uses 4-connected neighbors; outer-edge pixels can be masked and are exported as NoData'
  };
}

function exportRegion(region) {
  assertConfigured(region);
  var processingProjection = ee.Projection(region.processingCrs);
  var wgs84Proj = ee.Projection('EPSG:4326');
  
  // 用于投影转换的明确 1 米容差对象
  var err = ee.ErrorMargin(1);

  // 1. 获取最原始的 GEE 面几何
  var aoiRaw = ee.FeatureCollection(region.aoiAsset).geometry();
  
  // 2. 核心修正：先转换至米制处理坐标系 (UTM)，在这个过程中使用 err 确保不丢失精度
  // 转完后执行 dissolve，在 UTM 下输入纯数字 1 即代表 1 米容差
  var aoiUtm = aoiRaw.transform(processingProjection, err).dissolve(1);
  
  // 3. 执行缓冲：buffer 的 distance 和 maxError 现在都是普通数字 (5000 和 1)
  // 因为底图已是 UTM，GEE 会完美识别这两个数字同为“米”单位，不再报错
  var bufferedUtm = aoiUtm.buffer(CONFIG.bufferM, 1);
  
  // 4. 将处理好的边界转回 WGS84，用于最后 GeoJSON 的矢量导出
  var aoiWgs84 = aoiUtm.transform(wgs84Proj, err);
  var bufferedWgs84 = bufferedUtm.transform(wgs84Proj, err);

  // 在米制坐标系中建立统一 30 m 网格，再计算坡度和坡向。
  var demProjected = srtm
    .resample('bilinear')
    .reproject({
      crs: processingProjection,
      scale: CONFIG.outputScaleM
    })
    .rename('elevation');

  // 裁剪前计算，避免正式交付边界内因缺少邻域像元产生额外空值带。
  var terrain = ee.Terrain.products(demProjected);
  var dem = demProjected.clip(bufferedUtm).rename('elevation').toInt16();
  var slope = terrain.select('slope').clip(bufferedUtm).rename('slope').toFloat();
  var aspect = terrain.select('aspect').clip(bufferedUtm).rename('aspect').toFloat();

  var crsTag = region.processingCrs.toLowerCase().replace(':', '');
  var prefix = region.id + '_srtmgl1_003_30m_' + crsTag;
  var demName = prefix + '_dem';
  var slopeName = prefix + '_slope';
  var aspectName = prefix + '_aspect';
  var demMeta = baseMetadata(region, 'dem', 'elevation', 'm', demName, 'Int16');
  var slopeMeta = baseMetadata(region, 'slope', 'slope', 'degree', slopeName, 'Float32');
  var aspectMeta = baseMetadata(region, 'aspect', 'aspect', 'degree', aspectName, 'Float32');

  dem = dem.set(demMeta);
  slope = slope.set(slopeMeta);
  aspect = aspect.set(aspectMeta);

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

  exportRaster(dem, region.id + '_SRTM_DEM', demName);
  exportRaster(slope, region.id + '_SRTM_SLOPE', slopeName);
  exportRaster(aspect, region.id + '_SRTM_ASPECT', aspectName);

  // 同步保存正式 AOI 和 5 km 交付边界（使用上面第4步准备好的WGS84几何体）
  var boundaries = ee.FeatureCollection([
    ee.Feature(aoiWgs84, {
      region_id: region.id,
      region_name_zh: region.nameZh,
      boundary_type: 'confirmed_aoi',
      source_asset_id: region.aoiAsset,
      crs: 'EPSG:4326'
    }),
    ee.Feature(bufferedWgs84, {
      region_id: region.id,
      region_name_zh: region.nameZh,
      boundary_type: 'delivery_extent_aoi_plus_5km',
      source_asset_id: region.aoiAsset,
      buffer_m: CONFIG.bufferM,
      crs: 'EPSG:4326'
    })
  ]);

  Export.table.toDrive({
    collection: boundaries,
    description: region.id + '_SRTM_BOUNDARIES',
    folder: CONFIG.exportFolder,
    fileNamePrefix: region.id + '_srtm_boundaries',
    fileFormat: 'GeoJSON'
  });

  // 每个栅格一行，保存完整描述性元数据。
  var metadataTable = ee.FeatureCollection([
    ee.Feature(null, demMeta),
    ee.Feature(null, slopeMeta),
    ee.Feature(null, aspectMeta)
  ]);
  Export.table.toDrive({
    collection: metadataTable,
    description: region.id + '_SRTM_METADATA',
    folder: CONFIG.exportFolder,
    fileNamePrefix: region.id + '_srtm_metadata',
    fileFormat: 'CSV'
  });

  var combinedReducer = ee.Reducer.minMax()
    .combine({reducer2: ee.Reducer.mean(), sharedInputs: true})
    .combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true});

  function statsFor(image) {
    return image.reduceRegion({
      reducer: combinedReducer,
      geometry: bufferedUtm,
      crs: region.processingCrs,
      scale: CONFIG.outputScaleM,
      maxPixels: CONFIG.maxPixels,
      tileScale: 4
    });
  }

  var validPixelCount = demProjected.mask()
    .rename('valid')
    .clip(bufferedUtm)
    .reduceRegion({
      reducer: ee.Reducer.sum(),
      geometry: bufferedUtm,
      crs: region.processingCrs,
      scale: CONFIG.outputScaleM,
      maxPixels: CONFIG.maxPixels,
      tileScale: 4
    })
    .get('valid');

  var totalPixelCount = ee.Image.constant(1)
    .rename('total')
    .reproject({crs: processingProjection, scale: CONFIG.outputScaleM})
    .clip(bufferedUtm)
    .reduceRegion({
      reducer: ee.Reducer.count(),
      geometry: bufferedUtm,
      crs: region.processingCrs,
      scale: CONFIG.outputScaleM,
      maxPixels: CONFIG.maxPixels,
      tileScale: 4
    })
    .get('total');

  var statistics = ee.Feature(null, {
    region_id: region.id,
    region_name_zh: region.nameZh,
    source_asset_id: region.aoiAsset,
    processing_crs: region.processingCrs,
    output_resolution_m: CONFIG.outputScaleM,
    buffer_m: CONFIG.bufferM,
    aoi_area_m2: aoiUtm.area(1),             // 因为已经在 UTM 投影下，用纯数字 1 代表 1 米容差
    delivery_extent_area_m2: bufferedUtm.area(1), // 同上
    valid_dem_pixel_count: validPixelCount,
    total_pixel_count: totalPixelCount,
    valid_dem_coverage_percent: ee.Number(validPixelCount)
      .divide(ee.Number(totalPixelCount))
      .multiply(100),
    export_requested_at_utc: runTimestampUtc
  })
    .set(statsFor(dem))
    .set(statsFor(slope))
    .set(statsFor(aspect));

  Export.table.toDrive({
    collection: ee.FeatureCollection([statistics]),
    description: region.id + '_SRTM_STATISTICS',
    folder: CONFIG.exportFolder,
    fileNamePrefix: region.id + '_srtm_statistics',
    fileFormat: 'CSV'
  });

  Map.addLayer(
    dem,
    {min: 0, max: 1000, palette: ['0b3d91', '41ab5d', 'ffffbf', 'a6611a']},
    region.nameZh + ' DEM',
    false
  );
  Map.addLayer(
    slope,
    {min: 0, max: 45, palette: ['ffffff', 'fee08b', 'f46d43', 'a50026']},
    region.nameZh + ' 坡度',
    false
  );
  Map.addLayer(
    aspect,
    {min: 0, max: 360, palette: ['e41a1c', 'ff7f00', 'ffff33', '4daf4a', '377eb8', '984ea3', 'e41a1c']},
    region.nameZh + ' 坡向',
    false
  );
  Map.addLayer(
    boundaries.style({color: '00ffff', fillColor: '00000000', width: 2}),
    {},
    region.nameZh + ' AOI 与 5 km 边界',
    true
  );

  print(region.nameZh + ' metadata', metadataTable);
  print(region.nameZh + ' statistics', statistics);
  return bufferedUtm;
}

var exportExtentFeatures = [];
CONFIG.regions.forEach(function (region) {
  exportExtentFeatures.push(ee.Feature(exportRegion(region)));
});

Map.centerObject(ee.FeatureCollection(exportExtentFeatures), 8);
print('任务已建立。请在 Tasks 面板逐项检查并点击 Run。');
