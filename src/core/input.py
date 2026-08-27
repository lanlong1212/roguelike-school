"""
输入管理器模块。

功能说明：
    统一缓存键盘与鼠标状态，区分"持续按下"与"本帧刚按下"两种语义，
    供各状态在 update 中查询。每帧结束时由 Game 调用 end_frame()
    清空"刚按下"标记，保证一次性触发语义正确。
"""
import pygame


class InputManager:
    """输入状态缓存，提供键盘/鼠标查询接口。"""

    def __init__(self):
        self._keys_pressed = set()        # 当前持续按下的键集合
        self._keys_just_pressed = set()   # 本帧刚按下的键集合（下一帧清空）
        self._mouse_pos = (0, 0)          # 鼠标当前位置
        self._mouse_just_clicked = {1: False, 3: False}  # 本帧刚点击的鼠标键

    def handle_event(self, event):
        """处理 pygame 事件，更新内部缓存。由 Game 主循环每帧调用。"""
        if event.type == pygame.KEYDOWN:
            self._keys_pressed.add(event.key)
            self._keys_just_pressed.add(event.key)
        elif event.type == pygame.KEYUP:
            self._keys_pressed.discard(event.key)
        elif event.type == pygame.MOUSEMOTION:
            self._mouse_pos = event.pos
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button in self._mouse_just_clicked:
                self._mouse_just_clicked[event.button] = True

    # ========== 键盘查询 ==========

    def is_pressed(self, key):
        """查询某键是否持续按下（用于持续移动等）。"""
        return key in self._keys_pressed

    def is_just_pressed(self, key):
        """查询某键是否本帧刚按下（用于触发动作，如确认/取消）。"""
        return key in self._keys_just_pressed

    # ========== 鼠标查询 ==========

    def get_mouse_pos(self):
        """返回鼠标当前位置元组 (x, y)。"""
        return self._mouse_pos

    def is_mouse_just_clicked(self, button=1):
        """查询某鼠标键是否本帧刚点击（button: 1=左键, 3=右键）。"""
        return self._mouse_just_clicked.get(button, False)

    def end_frame(self):
        """帧末清空一次性标记，必须在每帧结束时调用。"""
        self._keys_just_pressed.clear()
        for button in self._mouse_just_clicked:
            self._mouse_just_clicked[button] = False
