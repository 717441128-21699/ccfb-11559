"""levelcheck — 平台跳跃关卡可通关性检查器。

按角色物理参数(跑速/起跳初速/重力/土狼时间/二段跳)批量模拟跳跃轨迹,
找出够不着的收集品和终点, 并给出移动平台的起跳时机窗口。
"""
from .physics import PhysicsParams
from .level import Level
from .reachability import check_level, CheckReport

__all__ = ["PhysicsParams", "Level", "check_level", "CheckReport"]
__version__ = "0.1.0"
