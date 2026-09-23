/**
 * 火巡智策：4 个规划展示区概览边界生成（Google Earth Engine）
 *
 * 规划展示区：
 *   1. 云台山
 *   2. 宁镇丘陵东段
 *   3. 宜溧山地
 *   4. 环太湖丘陵
 *
 * 重要语义：这些成果仅用于省级规划展示和区域索引，不是法定边界，
 * 也不得直接作为可执行调度、行政管理或自然保护地管控边界。
 *
 * 方法：
 *   - SRTM 高程 >= 30 m，或坡度 >= 5°；
 *   - 核心层采用树木覆盖 1 km 邻域与 800 m 连接半径；
 *   - 外轮廓采用树木覆盖 2.5 km 邻域与 2 km 连接半径；
 *   - 去除水体，并在 100 m 工作尺度进行形态闭运算和小斑块清理；
 *   - 使用权威资料确定的地理位置建立“种子窗口”；
 *   - 环太湖丘陵剔除宜溧山地结果，避免两个展示区重叠。
 *
 * 使用前：确认 CONFIG 中江苏省界 Asset ID 可访问。运行后在 Tasks 中
 * 启动 PLANNING_REGIONS_OVERVIEW_GEOJSON 导出任务。
 */

var CONFIG = {
  exportFolder: 'fire_patrol_planning_regions_v1',
  provinceAsset:
    'projects/my-project-260421-494009/assets/jiangsu_province_boundary_wgs84',

  analysisCrs: 'EPSG:3857',
  workingScaleM: 100,
  elevationThresholdM: 30,
  slopeThresholdDeg: 5,
  // 精细证据层：保留林地—丘陵核心斑块。
  coreTreeProximityM: 1000,
  coreMorphologyRadiusM: 800,
  coreSimplifyToleranceM: 100,

  // 规划展示层：连接近邻山体，形成可读的连续概览外轮廓。
  outlineTreeProximityM: 2500,
  outlineMorphologyRadiusM: 2000,
  outlineMinPatchAreaKm2: 3,
  outlineSimplifyToleranceM: 300,
  maxPixels: 1e10,
  tileScale: 8,

  // 由当前项目确认：仅作规划展示，不是执行调度区。
  planningDisplayOnly: true,
  verificationStatus: 'unverified',
  qaStatus: 'PENDING_LOCAL_QA'
};

var SOURCE = {
  demAssetId: 'USGS/SRTMGL1_003',
  demBand: 'elevation',
  demNativeResolutionM: 30,
  landcoverAssetId: 'ESA/WorldCover/v200',
  landcoverBand: 'Map',
  landcoverProductYear: 2021,
  landcoverNativeResolutionM: 10,
  treeClassValue: 10,
  waterClassValue: 80
};

// WGS84 种子窗口只是检索约束，不是交付边界。
// 它们依据官方地理描述覆盖目标山系，同时避免把全市行政区当成山地边界。
var REGION_SPECS = [
  {
    id: 'planning_yuntai',
    name: '云台山',
    bbox: [119.10, 34.50, 119.55, 34.85],
    minPatchAreaKm2: 0.5,
    boundaryType: 'derived_from_official_description_and_terrain',
    sourceBasis:
      '连云港市政府2018年云台山风景名胜区保护区界线通告及2026年规划范围说明；本成果未取得通告所述官方矢量，仅据地理范围与地形遥感派生',
    sourceUrl:
      'https://www.lyg.gov.cn/zglygzfmhwz/szfwj1/content/zwgk_504570641ccf418cb0190268320fdf20.html',
    officialBoundary: false
  },
  {
    id: 'planning_ningzhen_east',
    name: '宁镇丘陵东段',
    bbox: [119.05, 31.78, 119.82, 32.32],
    minPatchAreaKm2: 1.0,
    boundaryType: 'project_defined_overview',
    sourceBasis:
      '镇江市国土空间规划宁镇山脉生态涵养带、圌山为宁镇丘陵东段最高峰的官方地理说明及太湖流域宁镇丘陵岗地区分区',
    sourceUrl:
      'https://www.jiangsu.gov.cn/art/2023/8/31/art_46143_11000570.html',
    officialBoundary: false
  },
  {
    id: 'planning_yili',
    name: '宜溧山地',
    bbox: [119.15, 30.75, 120.05, 31.55],
    minPatchAreaKm2: 1.0,
    boundaryType: 'project_defined_overview',
    sourceBasis:
      '太湖流域宜溧低山丘陵区分区，以及宜兴南部—溧阳南部天目山余脉的官方地理描述',
    sourceUrl:
      'https://www.tba.gov.cn/slbthlyglj/upload/1b7e982e-bcbc-4c5c-88df-d2a163dc2893.pdf',
    officialBoundary: false
  },
  {
    id: 'planning_taihu_hills',
    name: '环太湖丘陵',
    bbox: [119.85, 30.75, 121.20, 31.85],
    minPatchAreaKm2: 0.5,
    boundaryType: 'project_defined_overview',
    sourceBasis:
      '江苏省国土空间规划太湖丘陵生态绿心、太湖流域太湖丘陵区及太湖风景名胜区山体景区；排除宜溧山地以避免重复',
    sourceUrl:
      'https://www.jiangsu.gov.cn/attach/0/786d533807a04e9a90babc20b27fcf90.pdf',
    officialBoundary: false
  }
];

var province = ee.FeatureCollection(CONFIG.provinceAsset);
var provinceGeometry = province.geometry().dissolve(100, CONFIG.analysisCrs);

var dem = ee.Image(SOURCE.demAssetId).select(SOURCE.demBand);
var slope = ee.Terrain.slope(dem);
var worldCover = ee.ImageCollection(SOURCE.landcoverAssetId)
  .first()
  .select(SOURCE.landcoverBand);

var terrainMask = dem.gte(CONFIG.elevationThresholdM)
  .or(slope.gte(CONFIG.slopeThresholdDeg));
var landMask = worldCover.neq(SOURCE.waterClassValue);
function bboxGeometry(bounds) {
  return ee.Geometry.Rectangle(bounds, 'EPSG:4326', false)
    .intersection(provinceGeometry, 100);
}

function buildCandidateGeometry(spec, options) {
  var searchGeometry = bboxGeometry(spec.bbox);
  var treeNearbyMask = worldCover.eq(SOURCE.treeClassValue).focalMax({
    radius: options.treeProximityM,
    kernelType: 'circle',
    units: 'meters'
  });

  var candidate = terrainMask
    .and(treeNearbyMask)
    .and(landMask)
    .clip(searchGeometry)
    .reproject({
      crs: CONFIG.analysisCrs,
      scale: CONFIG.workingScaleM
    });

  // 闭运算连接相邻的丘陵/林地斑块并填补小孔洞。
  candidate = candidate
    .focalMax({
      radius: options.morphologyRadiusM,
      kernelType: 'circle',
      units: 'meters'
    })
    .focalMin({
      radius: options.morphologyRadiusM,
      kernelType: 'circle',
      units: 'meters'
    })
    // 形态闭运算可能跨越狭窄水面，最终再次套用非水体掩膜。
    .and(landMask)
    .clip(searchGeometry)
    .selfMask()
    .rename('region_label')
    .toInt8();

  var vectors = candidate.reduceToVectors({
    geometry: searchGeometry,
    crs: CONFIG.analysisCrs,
    scale: CONFIG.workingScaleM,
    geometryType: 'polygon',
    eightConnected: true,
    labelProperty: 'region_label',
    reducer: ee.Reducer.countEvery(),
    bestEffort: false,
    maxPixels: CONFIG.maxPixels,
    tileScale: CONFIG.tileScale
  }).map(function (feature) {
    feature = ee.Feature(feature);
    return feature.set('patch_area_m2', feature.geometry().area(100));
  }).filter(ee.Filter.gte('patch_area_m2', options.minPatchAreaKm2 * 1e6));

  return vectors.geometry(100)
    .dissolve(100)
    .simplify(options.simplifyToleranceM);
}

function regionFeature(spec, geometry, layerRole, options) {
  var seed = spec.bbox.join(',');
  return ee.Feature(geometry, {
    region_id: spec.id,
    region_name_zh: spec.name,
    region_level: 'planning_display_region',
    layer_role: layerRole,
    planning_display_only: CONFIG.planningDisplayOnly,
    executable_dispatch_area: false,
    verification_status: CONFIG.verificationStatus,
    qa_status: CONFIG.qaStatus,
    boundary_type: spec.boundaryType,
    official_boundary: spec.officialBoundary,
    source_basis: spec.sourceBasis,
    source_url: spec.sourceUrl,
    derivation_method:
      'seed_window ∩ Jiangsu ∩ ((SRTM elevation>=30m OR slope>=5deg) ∩ tree_proximity ∩ non_water), 100m morphology and patch filtering',
    seed_bbox_wgs84: seed,
    elevation_threshold_m: CONFIG.elevationThresholdM,
    slope_threshold_deg: CONFIG.slopeThresholdDeg,
    tree_proximity_m: options.treeProximityM,
    morphology_radius_m: options.morphologyRadiusM,
    minimum_patch_area_km2: options.minPatchAreaKm2,
    working_resolution_m: CONFIG.workingScaleM,
    delivery_crs: 'EPSG:4326',
    source_dem: SOURCE.demAssetId,
    source_landcover: SOURCE.landcoverAssetId,
    source_landcover_year: SOURCE.landcoverProductYear,
    generated_at_utc: new Date().toISOString()
  });
}

var yuntaiSpec = REGION_SPECS[0];
var ningzhenSpec = REGION_SPECS[1];
var yiliSpec = REGION_SPECS[2];
var taihuSpec = REGION_SPECS[3];

function coreOptions(spec) {
  return {
    treeProximityM: CONFIG.coreTreeProximityM,
    morphologyRadiusM: CONFIG.coreMorphologyRadiusM,
    minPatchAreaKm2: spec.minPatchAreaKm2,
    simplifyToleranceM: CONFIG.coreSimplifyToleranceM
  };
}

function outlineOptions() {
  return {
    treeProximityM: CONFIG.outlineTreeProximityM,
    morphologyRadiusM: CONFIG.outlineMorphologyRadiusM,
    minPatchAreaKm2: CONFIG.outlineMinPatchAreaKm2,
    simplifyToleranceM: CONFIG.outlineSimplifyToleranceM
  };
}

var yuntaiCore = buildCandidateGeometry(yuntaiSpec, coreOptions(yuntaiSpec));
var ningzhenCore = buildCandidateGeometry(ningzhenSpec, coreOptions(ningzhenSpec));
var yiliCore = buildCandidateGeometry(yiliSpec, coreOptions(yiliSpec));
var taihuCore = buildCandidateGeometry(taihuSpec, coreOptions(taihuSpec))
  .difference(yiliCore, 100)
  .simplify(CONFIG.coreSimplifyToleranceM);

var yuntaiOutline = buildCandidateGeometry(yuntaiSpec, outlineOptions());
var ningzhenOutline = buildCandidateGeometry(ningzhenSpec, outlineOptions());
var yiliOutline = buildCandidateGeometry(yiliSpec, outlineOptions());
var taihuOutline = buildCandidateGeometry(taihuSpec, outlineOptions())
  .difference(yiliOutline, 100)
  .simplify(CONFIG.outlineSimplifyToleranceM);

// 核心证据层必须位于对应规划外轮廓内。
yuntaiCore = yuntaiCore.intersection(yuntaiOutline, 100);
ningzhenCore = ningzhenCore.intersection(ningzhenOutline, 100);
yiliCore = yiliCore.intersection(yiliOutline, 100);
taihuCore = taihuCore.intersection(taihuOutline, 100);

var planningRegions = ee.FeatureCollection([
  regionFeature(yuntaiSpec, yuntaiOutline, 'planning_region_outline', outlineOptions()),
  regionFeature(ningzhenSpec, ningzhenOutline, 'planning_region_outline', outlineOptions()),
  regionFeature(yiliSpec, yiliOutline, 'planning_region_outline', outlineOptions()),
  regionFeature(taihuSpec, taihuOutline, 'planning_region_outline', outlineOptions())
]);

var forestTerrainCores = ee.FeatureCollection([
  regionFeature(yuntaiSpec, yuntaiCore, 'forest_terrain_core', coreOptions(yuntaiSpec)),
  regionFeature(ningzhenSpec, ningzhenCore, 'forest_terrain_core', coreOptions(ningzhenSpec)),
  regionFeature(yiliSpec, yiliCore, 'forest_terrain_core', coreOptions(yiliSpec)),
  regionFeature(taihuSpec, taihuCore, 'forest_terrain_core', coreOptions(taihuSpec))
]);

print('规划展示区', planningRegions);
print('林地—丘陵核心', forestTerrainCores);
print('区域数量（应为4）', planningRegions.size());

Map.centerObject(province, 7);
Map.addLayer(province.style({color: '333333', fillColor: '00000000'}), {}, '江苏省界');
Map.addLayer(yuntaiOutline, {color: 'e41a1c'}, '云台山—规划外轮廓');
Map.addLayer(ningzhenOutline, {color: '377eb8'}, '宁镇丘陵东段—规划外轮廓');
Map.addLayer(yiliOutline, {color: '4daf4a'}, '宜溧山地—规划外轮廓');
Map.addLayer(taihuOutline, {color: '984ea3'}, '环太湖丘陵—规划外轮廓');
Map.addLayer(yuntaiCore, {color: 'ff9896'}, '云台山—核心', false);
Map.addLayer(ningzhenCore, {color: '9ecae1'}, '宁镇丘陵东段—核心', false);
Map.addLayer(yiliCore, {color: 'a1d99b'}, '宜溧山地—核心', false);
Map.addLayer(taihuCore, {color: 'c994c7'}, '环太湖丘陵—核心', false);

Export.table.toDrive({
  collection: planningRegions,
  description: 'PLANNING_REGIONS_OVERVIEW_GEOJSON',
  folder: CONFIG.exportFolder,
  fileNamePrefix: 'planning_regions_overview',
  fileFormat: 'GeoJSON'
});

Export.table.toDrive({
  collection: forestTerrainCores,
  description: 'PLANNING_REGIONS_FOREST_TERRAIN_CORE_GEOJSON',
  folder: CONFIG.exportFolder,
  fileNamePrefix: 'planning_regions_forest_terrain_core',
  fileFormat: 'GeoJSON'
});
