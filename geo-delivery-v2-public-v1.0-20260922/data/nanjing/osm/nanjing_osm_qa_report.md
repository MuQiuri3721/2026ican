# Nanjing OSM delivery QA report

- Generated at: `2026-09-21T10:48:14+00:00`
- Processing extent: Nanjing administrative boundary plus 5 km
- QA status: **PASS**
- Road edges: 476,701
- Road nodes: 440,588
- Water geometries: 9,400
- Water candidates: 9,400
- Facility candidates: 759
- Missing road-node references: 0
- Missing water-candidate parent links: 0
- Invalid or empty road geometries: 0
- Invalid or empty water geometries: 0
- Non-positive road lengths: 0
- Overlay image created: True

## Top road classes

- `service`: 82,694
- `unclassified`: 72,785
- `tertiary`: 62,472
- `footway`: 59,330
- `residential`: 50,265
- `secondary`: 32,250
- `primary`: 27,321
- `path`: 14,796
- `track`: 14,478
- `trunk`: 11,396
- `motorway_link`: 11,226
- `motorway`: 8,578
- `cycleway`: 5,792
- `living_street`: 5,652
- `trunk_link`: 5,442
- `pedestrian`: 4,237
- `primary_link`: 2,368
- `steps`: 2,077
- `tertiary_link`: 1,876
- `secondary_link`: 1,565

## Interpretation limits

Road connectivity follows shared OSM node IDs. Grade-separated crossings are not connected unless the source data shares a node. This is a reproducible candidate graph, not production-grade evacuation navigation.

Water and facility records are candidates. Unverified and null capability fields must not be promoted to usable or available without external evidence or field verification.
