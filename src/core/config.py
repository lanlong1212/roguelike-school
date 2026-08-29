"""
全局配置常量模块。

功能说明：
    集中定义游戏运行所需的全部静态常量，包括屏幕参数、瓦片规格、战斗数值、
    色彩调色板等。其他模块通过 from src.core import config 引用，便于
    统一调参与热改数值，避免硬编码散落各处。
"""

# ========== 屏幕参数 ==========
SCREEN_WIDTH = 1280          # 窗口宽度（像素）
SCREEN_HEIGHT = 720          # 窗口高度（像素）
FPS = 60                     # 目标帧率
FPS_MIN = 30                 # 最低可接受帧率（低于此值视为掉帧）
TITLE = "迷城棋局 Labyrinth Chess"  # 窗口标题

# ========== 瓦片规格 ==========
TILE_SIZE = 32               # 单个瓦片边长（像素）
ROOM_MAX_SIZE = 12           # 单个房间最大边长（瓦片数）
MAP_MAX_SIZE = 40            # 单层地图最大边长（瓦片数）
MAX_FLOOR_LEVEL = 3          # 游戏最大楼层数（达到后击败 Boss 即通关）

# ========== 战斗数值 ==========
AP_MAX = 5                   # 每回合行动点上限
MOVE_RANGE = 3               # 每回合移动格数上限

# ========== 经济系统 ==========
START_GOLD = 30              # 玩家初始金币
GOLD_SLIME = 3               # 史莱姆掉落金币
GOLD_SKELETON = 5            # 骷髅掉落金币
GOLD_BOSS = 20               # Boss 掉落金币
# 商店商品价格
SHOP_PRICE_IRON_SWORD = 20
SHOP_PRICE_LONG_BOW = 35
SHOP_PRICE_HEALTH_POTION = 10
SHOP_PRICE_STRENGTH_POTION = 25

# ========== 基础颜色 (R, G, B) ==========
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
DARK_GRAY = (40, 40, 50)     # 主背景色
LIGHT_GRAY = (200, 200, 200)

# ========== 地牢瓦片颜色 ==========
COLOR_WALL = (30, 30, 40)    # 墙壁
COLOR_FLOOR = (70, 60, 80)   # 地面
COLOR_DOOR = (120, 90, 50)   # 房门
COLOR_STAIR = (255, 235, 120)  # 下行阶梯

# ========== 实体颜色 ==========
COLOR_PLAYER = (80, 180, 255)   # 玩家
COLOR_ENEMY = (220, 80, 80)     # 普通敌人
COLOR_BOSS = (180, 40, 220)     # Boss

# ========== 战斗网格高亮颜色 (R, G, B, A) ==========
COLOR_MOVE_RANGE = (80, 180, 255, 80)     # 可移动范围（蓝）
COLOR_ATTACK_RANGE = (220, 80, 80, 80)    # 可攻击范围（红）
COLOR_SKILL_RANGE = (255, 220, 80, 80)    # 技能范围（黄）

# ========== UI 颜色 ==========
COLOR_HP = (220, 60, 60)              # 血条
COLOR_AP = (80, 180, 255)             # 行动点条
COLOR_TEXT = (230, 230, 230)          # 普通文字
COLOR_TEXT_HIGHLIGHT = (255, 220, 100) # 高亮文字
COLOR_PANEL = (20, 20, 30, 220)       # 半透明面板背景

# ========== 战争迷雾颜色 (R, G, B, A) ==========
COLOR_FOG_UNSEEN = (0, 0, 0, 255)     # 未探索：完全黑色
COLOR_FOG_EXPLORED = (0, 0, 0, 160)   # 已探索：半透明黑遮罩
