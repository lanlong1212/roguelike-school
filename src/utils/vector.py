"""
二维向量工具模块。

功能说明：
    提供 Vector2 不可变风格向量类，封装网格坐标与方向运算。
    用于实体位置、移动方向、距离计算等场景，替代裸 tuple 提升可读性。
    使用 __slots__ 减少内存占用，适合大量实体并存。
"""
import math


class Vector2:
    """二维向量。坐标用 float 存储，支持加减乘除与几何运算。"""

    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)

    # ========== 运算符重载 ==========

    def __add__(self, other):
        """向量加法：self + other → 新向量。"""
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        """向量减法：self - other → 新向量。"""
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        """标量乘法：self × 标量 → 新向量。"""
        return Vector2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__  # 支持标量 × 向量

    def __truediv__(self, scalar):
        """标量除法：self / 标量 → 新向量。"""
        return Vector2(self.x / scalar, self.y / scalar)

    def __eq__(self, other):
        """相等判断：两向量分量相等则相等。"""
        return self.x == other.x and self.y == other.y

    def __hash__(self):
        """哈希值：用于作为 dict 键或放入 set。"""
        return hash((self.x, self.y))

    def __repr__(self):
        """调试输出。"""
        return f"Vector2({self.x}, {self.y})"

    # ========== 转换方法 ==========

    def to_tuple(self):
        """转换为 float 元组，用于 pygame 绘制接口。"""
        return (self.x, self.y)

    def to_int_tuple(self):
        """转换为 int 元组，用于网格坐标索引。"""
        return (int(self.x), int(self.y))

    # ========== 几何运算 ==========

    def distance_to(self, other):
        """计算到另一向量的欧几里得距离。"""
        return math.hypot(self.x - other.x, self.y - other.y)

    def length(self):
        """计算自身模长（到原点距离）。"""
        return math.hypot(self.x, self.y)

    def normalized(self):
        """返回单位向量；零向量返回零向量避免除零。"""
        length = self.length()
        if length == 0:
            return Vector2(0, 0)
        return Vector2(self.x / length, self.y / length)

    def copy(self):
        """返回副本，避免共享引用。"""
        return Vector2(self.x, self.y)
