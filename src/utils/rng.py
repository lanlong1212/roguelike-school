"""
随机数工具模块。

功能说明：
    封装带种子的随机数生成器，确保同一种子产生完全相同的随机序列。
    用于程序化地图生成、物品掉落、AI 决策等场景，支持"种子复现"
    和"种子分享"功能——玩家可输入相同种子重现同一局地牢。
"""
import random


class RNG:
    """带种子的随机数封装，基于 random.Random 实例隔离随机状态。"""

    def __init__(self, seed=None):
        # 未指定种子时自动生成一个，记录后可回溯
        self.seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        self._rng = random.Random(self.seed)

    def reseed(self, seed):
        """重置种子，重新初始化随机序列。用于同一局内分阶段重置。"""
        self.seed = seed
        self._rng = random.Random(seed)

    # ========== 基础随机接口 ==========

    def random(self):
        """返回 [0.0, 1.0) 区间浮点数。"""
        return self._rng.random()

    def randint(self, a, b):
        """返回 [a, b] 闭区间整数。"""
        return self._rng.randint(a, b)

    def uniform(self, a, b):
        """返回 [a, b] 区间浮点数。"""
        return self._rng.uniform(a, b)

    # ========== 序列操作接口 ==========

    def choice(self, seq):
        """从序列中随机选取一个元素。"""
        return self._rng.choice(seq)

    def shuffle(self, seq):
        """原地打乱序列并返回，用于洗牌房间/物品顺序。"""
        self._rng.shuffle(seq)
        return seq

    def sample(self, population, k):
        """从总体中无重复抽取 k 个元素，用于随机选取房间类型。"""
        return self._rng.sample(population, k)
