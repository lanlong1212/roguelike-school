"""带种子的随机数封装，支持可复现的游戏局。"""
import random


class RNG:
    def __init__(self, seed=None):
        self.seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        self._rng = random.Random(self.seed)

    def reseed(self, seed):
        self.seed = seed
        self._rng = random.Random(seed)

    def random(self):
        return self._rng.random()

    def randint(self, a, b):
        return self._rng.randint(a, b)

    def uniform(self, a, b):
        return self._rng.uniform(a, b)

    def choice(self, seq):
        return self._rng.choice(seq)

    def shuffle(self, seq):
        self._rng.shuffle(seq)
        return seq

    def sample(self, population, k):
        return self._rng.sample(population, k)
