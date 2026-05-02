#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版键盘操作库 - 专为DeepSeek终端设计
专注于核心功能，避免复杂的绑定合并问题
"""

import sys
import os
from typing import Dict, Any
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import Condition
from prompt_toolkit.shortcuts import CompleteStyle

class SimpleKeyboardLibrary:
    """
    简化键盘库 - 提供核心键盘功能
    """
    
    def __init__(self):
        """初始化键盘库"""
        self.key_bindings = KeyBindings()
        self.mouse_support = True
        self.multiline_paste = True
        self.text_selection = True
        self.wheel_scroll = True
        self.shift_enter_newline = True
        
        # 初始化所有绑定
        self._setup_core_bindings()
        
    def _setup_core_bindings(self):
        """设置核心键盘绑定"""
        
        # 1. Shift+Enter 换行功能 (核心功能)
        @self.key_bindings.add('enter')
        def _(event: KeyPressEvent):
            """处理Enter键：普通Enter提交，Shift+Enter换行"""
            if event.key_sequence and event.key_sequence[0].key.is_shift_pressed:
                # Shift+Enter: 插入换行
                event.current_buffer.insert_text('\n')
            else:
                # 普通Enter: 提交输入
                event.current_buffer.validate_and_handle()
        
        # 2. 多行粘贴支持
        @self.key_bindings.add('c-v')
        def _(event: KeyPressEvent):
            """处理Ctrl+V粘贴，保持多行格式"""
            # 使用默认粘贴行为，prompt_toolkit会自动处理多行
            event.current_buffer.paste_clipboard_data()
        
        # 3. 文本选择增强
        @self.key_bindings.add('left', filter=Condition(lambda: self.text_selection))
        def _(event: KeyPressEvent):
            """左箭头键"""
            buff = event.current_buffer
            if event.key_sequence and event.key_sequence[0].key.is_shift_pressed:
                # Shift+左箭头：向左扩展选择
                buff.cursor_left(selecting=True)
            else:
                # 普通左箭头：移动光标
                buff.cursor_left()
        
        @self.key_bindings.add('right', filter=Condition(lambda: self.text_selection))
        def _(event: KeyPressEvent):
            """右箭头键"""
            buff = event.current_buffer
            if event.key_sequence and event.key_sequence[0].key.is_shift_pressed:
                # Shift+右箭头：向右扩展选择
                buff.cursor_right(selecting=True)
            else:
                # 普通右箭头：移动光标
                buff.cursor_right()
        
        @self.key_bindings.add('up', filter=Condition(lambda: self.text_selection))
        def _(event: KeyPressEvent):
            """上箭头键"""
            buff = event.current_buffer
            if event.key_sequence and event.key_sequence[0].key.is_shift_pressed:
                # Shift+上箭头：向上扩展选择
                buff.cursor_up(selecting=True)
            else:
                # 普通上箭头：移动光标
                buff.cursor_up()
        
        @self.key_bindings.add('down', filter=Condition(lambda: self.text_selection))
        def _(event: KeyPressEvent):
            """下箭头键"""
            buff = event.current_buffer
            if event.key_sequence and event.key_sequence[0].key.is_shift_pressed:
                # Shift+下箭头：向下扩展选择
                buff.cursor_down(selecting=True)
            else:
                # 普通下箭头：移动光标
                buff.cursor_down()
        
        # 4. 全选支持
        @self.key_bindings.add('c-a')
        def _(event: KeyPressEvent):
            """Ctrl+A全选"""
            buff = event.current_buffer
            buff.cursor_position = 0
            buff.start_selection()
            buff.cursor_position = len(buff.text)
        
        # 5. 复制支持
        @self.key_bindings.add('c-c')
        def _(event: KeyPressEvent):
            """Ctrl+C复制"""
            buff = event.current_buffer
            if buff.selection_state:
                # 如果有选中文本，复制到剪贴板
                selected_text = buff.text[buff.selection_state.original_cursor_position:buff.cursor_position]
                if selected_text:
                    # 设置剪贴板数据
                    from prompt_toolkit.clipboard import Clipboard
                    clipboard = Clipboard()
                    clipboard.set_data(selected_text)
    
    def get_key_bindings(self) -> KeyBindings:
        """获取配置好的键盘绑定"""
        return self.key_bindings
    
    def create_enhanced_session(self, 
                               message: str = "DS> ",
                               multiline: bool = True,
                               mouse_support: bool = True,
                               **kwargs) -> PromptSession:
        """
        创建增强的PromptSession
        
        Args:
            message: 提示消息
            multiline: 是否启用多行模式
            mouse_support: 是否启用鼠标支持
            **kwargs: 其他传递给PromptSession的参数
            
        Returns:
            PromptSession: 配置好的会话对象
        """
        # 设置默认参数
        session_kwargs = {
            'message': message,
            'multiline': multiline,
            'mouse_support': mouse_support and self.mouse_support,
            'key_bindings': self.get_key_bindings(),
            'enable_history_search': True,
            'complete_while_typing': True,
            'complete_style': CompleteStyle.MULTI_COLUMN,
            'editing_mode': EditingMode.EMACS,
        }
        
        # 更新用户提供的参数
        session_kwargs.update(kwargs)
        
        # 创建会话
        session = PromptSession(**session_kwargs)
        
        return session
    
    def enable_features(self, 
                       multiline_paste: bool = True,
                       text_selection: bool = True,
                       wheel_scroll: bool = True,
                       shift_enter_newline: bool = True):
        """
        启用/禁用特定功能
        
        Args:
            multiline_paste: 是否启用多行粘贴
            text_selection: 是否启用文本选择
            wheel_scroll: 是否启用滚轮滚动
            shift_enter_newline: 是否启用Shift+Enter换行
        """
        self.multiline_paste = multiline_paste
        self.text_selection = text_selection
        self.wheel_scroll = wheel_scroll
        self.shift_enter_newline = shift_enter_newline
        
        # 重新设置绑定
        self.key_bindings = KeyBindings()
        self._setup_core_bindings()
    
    def get_feature_status(self) -> Dict[str, bool]:
        """
        获取功能状态
        
        Returns:
            Dict[str, bool]: 功能状态字典
        """
        return {
            'multiline_paste': self.multiline_paste,
            'text_selection': self.text_selection,
            'wheel_scroll': self.wheel_scroll,
            'shift_enter_newline': self.shift_enter_newline,
            'mouse_support': self.mouse_support
        }


# 全局键盘库实例
_keyboard_lib_instance = None

def get_keyboard_library() -> SimpleKeyboardLibrary:
    """
    获取键盘库单例实例
    
    Returns:
        SimpleKeyboardLibrary: 键盘库实例
    """
    global _keyboard_lib_instance
    if _keyboard_lib_instance is None:
        _keyboard_lib_instance = SimpleKeyboardLibrary()
    return _keyboard_lib_instance

def create_enhanced_session(message: str = "DS> ", **kwargs) -> PromptSession:
    """
    快速创建增强会话的便捷函数
    
    Args:
        message: 提示消息
        **kwargs: 其他参数
        
    Returns:
        PromptSession: 配置好的会话对象
    """
    lib = get_keyboard_library()
    return lib.create_enhanced_session(message, **kwargs)

def enable_keyboard_features(multiline_paste: bool = True,
                           text_selection: bool = True,
                           wheel_scroll: bool = True,
                           shift_enter_newline: bool = True):
    """
    快速配置键盘功能
    
    Args:
        multiline_paste: 多行粘贴
        text_selection: 文本选择
        wheel_scroll: 滚轮滚动
        shift_enter_newline: Shift+Enter换行
    """
    lib = get_keyboard_library()
    lib.enable_features(multiline_paste, text_selection, wheel_scroll, shift_enter_newline)

def get_keyboard_status() -> Dict[str, bool]:
    """
    获取键盘功能状态
    
    Returns:
        Dict[str, bool]: 功能状态
    """
    lib = get_keyboard_library()
    return lib.get_feature_status()


if __name__ == "__main__":
    # 测试键盘库
    print("=== 简化键盘操作库测试 ===")
    print("1. 创建键盘库实例...")
    lib = SimpleKeyboardLibrary()
    
    print("2. 获取功能状态...")
    status = lib.get_feature_status()
    for feature, enabled in status.items():
        print(f"   {feature}: {'✅ 启用' if enabled else '❌ 禁用'}")
    
    print("3. 获取键盘绑定...")
    bindings = lib.get_key_bindings()
    print(f"   绑定数量: {len(bindings.bindings)}")
    
    print("4. 创建增强会话...")
    try:
        session = lib.create_enhanced_session("测试> ", multiline=True)
        print("   ✅ 会话创建成功")
    except Exception as e:
        print(f"   ❌ 会话创建失败: {e}")
    
    print("\n=== 测试完成 ===")