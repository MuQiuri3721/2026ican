# Unified areas.geojson QA report

- Generated at UTC: `2026-09-22T13:24:39.312831+00:00`
- QA status: **PASS**
- Feature count: 19
- Composition: Jiangsu province 1, prefectures 13, Nanjing detailed delivery region 1, planning-display regions 4.

## Checks

- PASS `feature_count_19`
- PASS `unique_region_ids`
- PASS `province_count_1`
- PASS `prefecture_count_13`
- PASS `prefecture_codes_complete`
- PASS `prefecture_union_matches_province`
- PASS `detailed_delivery_count_1`
- PASS `nanjing_delivery_matches_prefecture`
- PASS `planning_count_4`
- PASS `planning_regions_within_jiangsu_tolerance`
- PASS `required_properties_complete`
- PASS `all_geometries_valid`
- PASS `all_geometries_nonempty`
- PASS `all_delivery_crs_epsg4326`
- PASS `planning_marked_nonofficial`
- PASS `nanjing_delivery_parent_correct`

## Spatial consistency metrics

- Prefecture union outside province ratio: `0.000000000000`
- Province area uncovered by prefecture union ratio: `0.000000000000`
- Nanjing delivery/prefecture symmetric-difference ratio: `0.000009105841`
- Maximum planning-region area outside Jiangsu ratio: `0.000039043646`

## Semantics

Administrative, detailed-delivery and planning-display records are deliberately separate. The Nanjing detailed-delivery polygon is unbuffered; its 5 km technical processing extent remains in the module boundary file. The four planning regions are project-derived overview boundaries and cannot be presented as statutory or executable dispatch areas.
