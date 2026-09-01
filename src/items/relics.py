"""
遗物系统数据定义模块。

功能说明：
    定义全部遗物（Relic）数据：ID、中文名、效果描述、图标映射。
    遗物为跨战斗持续生效的强力被动，通过精英/Boss 掉落、商店购买获得。
    本模块仅定义数据，效果逻辑由 damage.py / battle_manager.py 等按 ID 触发。

数据约定：
    RELICS: dict[str, dict]，键为遗物 ID，值为包含
        name        中文显示名
        description 效果简述（tooltip / 背包 / 图鉴共用）
        icon        图标标识（当前为 None，后续 UI 步骤填充素材映射）
        color       占位图标底色（无素材时 UI 色块用，后续可替换素材）
        short       占位图标单字（无素材时 UI 文字用，后续可替换素材）
"""
from __future__ import annotations

from typing import Any

# 注：为避免与 player.py（本模块函数被其动态导入）形成静态循环依赖，
# 玩家对象参数统一以 Any 注解；运行时不导入 player 模块。


# ========== 遗物清单（8 个） ==========
# 注：docs/遗物系统 中 echo（回响）/ decoy（诱饵）为备选，暂不实现。
RELICS: dict[str, dict] = {
    "light_boots": {
        "name": "轻羽靴",
        "description": "每回合首次移动不消耗 AP",
        "icon": None,
        "color": (140, 200, 255),   # 浅蓝
        "short": "靴",
    },
    "element_echo": {
        "name": "元素共鸣",
        "description": "元素反应伤害 ×1.2",
        "icon": None,
        "color": (180, 130, 255),   # 紫
        "short": "鸣",
    },
    "war_drum": {
        "name": "击战鼓",
        "description": "击杀敌人回复 1 AP",
        "icon": None,
        "color": (220, 140, 90),    # 红棕
        "short": "鼓",
    },
    "guardian_charm": {
        "name": "守护符",
        "description": "每层首次受伤免疫伤害",
        "icon": None,
        "color": (255, 215, 120),   # 金
        "short": "符",
    },
    "fire_seed": {
        "name": "火种",
        "description": "火元素技能伤害 ×1.25",
        "icon": None,
        "color": (255, 120, 60),    # 红橙
        "short": "火",
    },
    "ice_heart": {
        "name": "冰心",
        "description": "被近战攻击后 50% 冻结攻击者 1 回合",
        "icon": None,
        "color": (150, 220, 255),   # 冰蓝
        "short": "冰",
    },
    "giant_power": {
        "name": "巨人之力",
        "description": "攻击 +3，最大 AP -1",
        "icon": None,
        "color": (200, 120, 120),   # 灰红
        "short": "力",
    },
    "greedy_eye": {
        "name": "贪婪之眼",
        "description": "击杀金币掉落翻倍",
        "icon": None,
        "color": (255, 200, 60),    # 金黄
        "short": "眼",
    },
}


def get_relic(relic_id: str) -> dict | None:
    """按 ID 查询遗物数据；不存在返回 None。"""
    return RELICS.get(relic_id)


def get_relic_name(relic_id: str) -> str:
    """按 ID 取遗物中文名（用于飘字提示等）。"""
    relic = RELICS.get(relic_id)
    return relic["name"] if relic else relic_id


def apply_relic_effect(player: "Player", relic_id: str) -> None:
    """获得遗物时的立即生效属性修改（目前仅巨人之力）。

    被动类遗物（轻羽靴/元素共鸣/火种等）由伤害/移动结算时按 ID 查询触发，
    不在本函数处理。新增"获得即改属性"的遗物时在此追加分支。
    """
    if relic_id == "giant_power":
        # 巨人之力：攻击 +3，最大 AP -1（不低于 1，避免 AP 归零无法行动）
        player.stats.atk += 3
        player.stats.max_ap = max(1, player.stats.max_ap - 1)


def revert_relic_effect(player: Any, relic_id: str) -> None:
    """反向还原"获得即改属性"遗物的加成（读档重放前回基础值用）。

    与 apply_relic_effect 一一对应；目前仅巨人之力：
    攻击 -3，最大 AP +1（原效果不触发下限截断，可直接还原）。
    新增"获得即改属性"的遗物时须同时补充本函数的反向分支。
    """
    if relic_id == "giant_power":
        player.stats.atk -= 3
        player.stats.max_ap += 1


def grant_relic(player: Any, relic_id: str) -> bool:
    """将遗物授予玩家（掉落/商店共用入口）。

    - 已拥有则返回 False（重复保护由调用方提前过滤，此处兜底）
    - 加入携带列表与已拥有集合，并应用立即生效的属性修改
    """
    if relic_id in player.relics or relic_id not in RELICS:
        return False
    player.relics.append(relic_id)
    player.owned_relics.add(relic_id)
    apply_relic_effect(player, relic_id)
    return True
