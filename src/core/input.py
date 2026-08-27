"""输入管理器：缓存键盘/鼠标状态，提供查询接口。"""
import pygame


class InputManager:
    def __init__(self):
        self._keys_pressed = set()
        self._keys_just_pressed = set()
        self._mouse_pos = (0, 0)
        self._mouse_just_clicked = {1: False, 3: False}

    def handle_event(self, event):
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

    def is_pressed(self, key):
        return key in self._keys_pressed

    def is_just_pressed(self, key):
        return key in self._keys_just_pressed

    def get_mouse_pos(self):
        return self._mouse_pos

    def is_mouse_just_clicked(self, button=1):
        return self._mouse_just_clicked.get(button, False)

    def end_frame(self):
        self._keys_just_pressed.clear()
        for button in self._mouse_just_clicked:
            self._mouse_just_clicked[button] = False
