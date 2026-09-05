"""多 Agent 协作层：6 个角色 Agent（规则算数字 · Agent 做研判 · 人类做审批）。"""
from .approver import APPROVER
from .commander import COMMANDER
from .recon import RECON
from .simulator import SIMULATOR
from .suppression import SUPPRESSION
from .support import SUPPORT

AGENTS = [COMMANDER, RECON, SUPPRESSION, SUPPORT, SIMULATOR, APPROVER]

__all__ = ["AGENTS", "APPROVER", "COMMANDER", "RECON", "SIMULATOR", "SUPPRESSION", "SUPPORT"]
