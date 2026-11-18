"""levelcheck —— 2D 平台跳跃关卡通关静态校验工具。

模块划分::

    physics   物理常数与纯数学工具(抛物线解析解、相位函数)
    level     关卡数据模型、JSON 解析、自检
    simulate  角色状态机与固定步长碰撞积分(游戏侧共用同一份 step)
    analyzer  落脚点可达性 BFS、跳跃弧线枚举、移动平台相位分析
    report    报告数据模型与文本 / JSON / Markdown 渲染
    cli       命令行入口
"""

from .analyzer import analyze_level, AnalysisResult
from .level import Level, LevelError, load_level
from .physics import PhysicsConfig

__all__ = [
    "analyze_level",
    "AnalysisResult",
    "Level",
    "LevelError",
    "load_level",
    "PhysicsConfig",
]

__version__ = "1.0.0"
