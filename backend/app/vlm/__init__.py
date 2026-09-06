"""VLM 视觉分析层（对照 docs/VLM队员执行手册.md）。

- prompts.py：冻结系统提示词 V1 与用户消息模板（prompt_version 随修改递增）
- contract.py：vlm-analysis-v1 结构校验 + §4.3 禁项守卫（剥除+标注，不阻断）
- client.py：glm-4.6v-flash 标准 API 直连客户端（FIRE_VLM_API_KEY）
"""

from .client import ImageUnreadable, vlm_analyze_images, vlm_client_status
from .contract import SCHEMA_VERSION, validate_vlm_analysis

__all__ = [
    "SCHEMA_VERSION",
    "ImageUnreadable",
    "vlm_analyze_images",
    "vlm_client_status",
    "validate_vlm_analysis",
]
