"""e2e 目录不是 pytest 测试目录。

裸 `pytest`（不带路径）按默认模式 `*_test.py` 会把本目录的独立脚本当测试模块
import：_fire_mapping_test/_real_vlm_test/full_function_test 都是模块级执行体
（长跑循环甚至模块级 sys.exit），收集阶段就会跑满 24 分钟并炸掉整个套件
（"no tests ran"）。这些脚本一律用 `python e2e/<脚本>.py` 直接运行。
"""
collect_ignore_glob = ["*_test.py"]
