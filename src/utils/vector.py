"""二维向量类。"""
import math


class Vector2:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)

    def __add__(self, other):
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return Vector2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return Vector2(self.x / scalar, self.y / scalar)

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def __hash__(self):
        return hash((self.x, self.y))

    def __repr__(self):
        return f"Vector2({self.x}, {self.y})"

    def to_tuple(self):
        return (self.x, self.y)

    def to_int_tuple(self):
        return (int(self.x), int(self.y))

    def distance_to(self, other):
        return math.hypot(self.x - other.x, self.y - other.y)

    def length(self):
        return math.hypot(self.x, self.y)

    def normalized(self):
        length = self.length()
        if length == 0:
            return Vector2(0, 0)
        return Vector2(self.x / length, self.y / length)

    def copy(self):
        return Vector2(self.x, self.y)
