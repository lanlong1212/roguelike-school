"""
存档管理模块。

功能说明：
    以 JSON 文件形式保存/读取/清除游戏进度。用于第二阶段"存档系统"。
    保存的内容包含：当前楼层、楼层种子（用于复现地牢）、玩家位置与属性
    （不含武器加成的基础值）、背包物品、已装备武器、击杀数。

设计考量：
    武器对属性的加成卸载时是"减回去"，因此保存时存基础属性，读取时
    先恢复基础属性，再重新挂装备武器由 Inventory 重新应用加成，避免重复累加。
"""
from __future__ import annotations

import os
import json

from typing import Any

# 存档目录与文件
SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "saves")
SAVE_FILE = os.path.join(SAVE_DIR, "save.json")


def _ensure_dir() -> None:
    """确保存档目录存在。"""
    os.makedirs(SAVE_DIR, exist_ok=True)


# ========== 物品工厂注册表 ==========

def _create_item(item_id: str):
    """按物品 id 创建对应物品实例。用于从存档反序列化物品。"""
    from src.items.potion import HealthPotion, StrengthPotion
    from src.items.weapon import create_iron_sword, create_long_bow
    factories = {
        "iron_sword": create_iron_sword,
        "long_bow": create_long_bow,
        "health_potion": HealthPotion,
        "strength_potion": StrengthPotion,
    }
    factory = factories.get(item_id)
    if factory is None:
        raise ValueError(f"无法识别的物品 id: {item_id}")
    return factory()


# ========== 玩家状态序列化 ==========

def _serialize_stats(player) -> dict:
    """序列化玩家基础属性（剔除当前武器提供的加成）。"""
    inv = player.inventory
    mod = inv._weapon_mod
    def _base(value, bonus):
        return value - (bonus if (mod and bonus) else 0)
    return {
        "hp": player.stats.hp,
        "max_hp": max(1, _base(player.stats.max_hp, mod.max_hp_bonus if mod else 0)),
        "atk": max(0, _base(player.stats.atk, mod.atk_bonus if mod else 0)),
        "def_": max(0, _base(player.stats.def_, mod.def_bonus if mod else 0)),
    }


def _serialize_inventory(player) -> tuple[list, str | None]:
    """序列化背包物品列表与已装备武器 id。"""
    items = []
    for slot in player.inventory.slots:
        if slot is not None:
            items.append({"id": slot.id, "count": slot.count})
    equipped_id = (
        player.inventory.equipped_weapon.id
        if player.inventory.equipped_weapon is not None
        else None
    )
    return items, equipped_id


# ========== 公开接口 ==========

def save_game(
    player,
    level: int,
    floor_seed: int,
    pos,
    kills: int,
    cleared_rooms=None,
) -> None:
    """把当前游戏进度写入存档。cleared_rooms 为已清空房间中心坐标集合。"""
    items, equipped_id = _serialize_inventory(player)
    data = {
        "version": 1,
        "level": level,
        "floor_seed": floor_seed,
        "player": {
            "x": int(pos.x),
            "y": int(pos.y),
            **_serialize_stats(player),
        },
        "inventory": items,
        "equipped_weapon": equipped_id,
        "kills": kills,
        "cleared_rooms": [list(c) for c in (cleared_rooms or set())],
    }
    _ensure_dir()
    tmp = SAVE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SAVE_FILE)


def load_game() -> dict | None:
    """读取存档，无存档或损坏时返回 None。"""
    if not os.path.exists(SAVE_FILE):
        return None
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def has_save() -> bool:
    """是否存在有效存档。"""
    return load_game() is not None


def apply_save_to_player(player, data: dict) -> None:
    """把存档数据恢复到玩家对象（属性、背包、装备）。"""
    p = data["player"]
    player.stats.max_hp = p["max_hp"]
    player.stats.hp = min(p["hp"], p["max_hp"])
    player.stats.atk = p["atk"]
    player.stats.def_ = p["def_"]

    # 恢复背包物品
    for entry in data.get("inventory", []):
        item = _create_item(entry["id"])
        item.count = entry.get("count", 1)
        player.inventory.add(item)

    # 恢复已装备武器（由 Inventory.equip_weapon 重新应用加成）
    equipped_id = data.get("equipped_weapon")
    if equipped_id:
        weapon = _create_item(equipped_id)
        player.inventory.equip_weapon(weapon)


def clear_save() -> None:
    """清除存档（死亡/胜利结算时调用）。"""
    if os.path.exists(SAVE_FILE):
        os.remove(SAVE_FILE)