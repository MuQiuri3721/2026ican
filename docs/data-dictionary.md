# 数据字典

| 数据 | 关键字段 | 来源 |
|---|---|---|
| 场景 | scene_id、wind_speed、wind_direction、terrain、water_sources | data/scene.json |
| 无人机 | id、role、battery、payload、status | data/fleet.json |
| 物资 | water_liters、dry_powder_kg、nearby_water_available | data/inventory.json |
| 火情 | fire_area_m2、smoke_area_m2、growth_rate、level | 规则管线/未来 YOLO |
| 调度 | can_control、material_amount、required_drones、tasks | 规则管线 |
| 监测 | next_fire_area_m2、action、reason | /api/monitor |
