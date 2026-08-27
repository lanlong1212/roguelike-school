"""游戏入口。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.game import Game
from src.states.menu_state import MenuState


def main():
    game = Game()
    game.push_state(MenuState(game))
    game.run()


if __name__ == "__main__":
    main()
