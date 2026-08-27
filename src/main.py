"""
游戏入口模块。

功能说明：
    程序启动点。将项目根目录加入 sys.path 以保证 src 包可被正确 import，
    然后实例化 Game、压入 MenuState 作为初始状态、启动主循环。
    运行方式：python src/main.py
"""
import os
import sys

# 将项目根目录加入搜索路径，保证 src.* 导入生效，如果main.py不在src里，就不用加这一条
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.game import Game
from src.states.menu_state import MenuState


def main():
    """创建游戏实例，以主菜单为初始状态，启动主循环。"""
    game = Game()
    game.push_state(MenuState(game))
    game.run()


if __name__ == "__main__":
    main()


