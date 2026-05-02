#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端输入框框架 - 跨平台兼容解决方案

解决固定底部输入框问题，支持：
1. 多终端兼容（Warp、Windows Terminal、iTerm2、GNOME Terminal等）
2. 动态边框保护
3. 光标位置锁定
4. 输出边界检测
5. 粘贴内容处理
"""

import sys
import os
import threading
import time
import shutil
from typing import Optional, Tuple, Callable
from dataclasses import dataclass


@dataclass
class TerminalInfo:
    """终端信息"""
    name: str = "unknown"
    width: int = 80
    height: int = 24
    supports_scroll_region: bool = True
    supports_save_restore_cursor: bool = True
    ansi_color: bool = True
    is_warp: bool = False
    is_windows_terminal: bool = False
    is_iterm: bool = False


class TerminalDetector:
    """终端检测器"""
    
    @staticmethod
    def detect() -> TerminalInfo:
        """检测终端类型和能力"""
        info = TerminalInfo()
        
        # 检测终端类型
        term_program = os.environ.get('TERM_PROGRAM', '').lower()
        term = os.environ.get('TERM', '').lower()
        
        info.is_warp = 'warp' in term_program
        info.is_windows_terminal = 'windowsterminal' in term_program or 'windows terminal' in term_program.lower()
        info.is_iterm = 'iterm' in term_program or 'iterm' in term
        
        if info.is_warp:
            info.name = "Warp Terminal"
        elif info.is_windows_terminal:
            info.name = "Windows Terminal"
        elif info.is_iterm:
            info.name = "iTerm2"
        elif 'gnome' in term:
            info.name = "GNOME Terminal"
        elif 'konsole' in term:
            info.name = "Konsole"
        elif sys.platform == 'win32':
            info.name = "Windows Console"
        else:
            info.name = term_program or term or "Unknown"
        
        # 获取终端尺寸
        try:
            size = shutil.get_terminal_size()
            info.width = size.columns
            info.height = size.lines
        except:
            info.width = 80
            info.height = 24
        
        # 检测ANSI支持能力（简化检测）
        # Warp终端可能有特殊行为
        if info.is_warp:
            info.supports_scroll_region = True  # Warp应该支持
            info.supports_save_restore_cursor = True
        elif sys.platform == 'win32' and not info.is_windows_terminal:
            # Windows旧版控制台可能支持有限
            info.supports_scroll_region = False
            info.supports_save_restore_cursor = False
        
        return info


class SafeOutput:
    """安全输出包装器"""
    
    def __init__(self, terminal_info: TerminalInfo):
        self.info = terminal_info
        self._output_lock = threading.RLock()
        self._line_count = 0
        self._max_scroll_lines = 0
        
    def write(self, text: str, ensure_position: bool = True) -> None:
        """安全的终端输出"""
        with self._output_lock:
            # 计算输出行数（近似）
            lines = text.count('\n') + (1 if text and not text.endswith('\n') else 0)
            self._line_count += lines
            
            # 检查是否需要滚动保护
            if self._max_scroll_lines > 0 and self._line_count >= self._max_scroll_lines - 5:
                # 接近边界，主动滚动一行
                self._scroll_up_one_line()
                self._line_count -= 1
            
            # 实际输出
            sys.stdout.write(text)
            sys.stdout.flush()
    
    def _scroll_up_one_line(self) -> None:
        """向上滚动一行（保护边框）"""
        if self.info.supports_scroll_region:
            # 使用ANSI序列向上滚动
            sys.stdout.write("\033[S")  # 向上滚动一行
            sys.stdout.flush()
    
    def reset_line_count(self) -> None:
        """重置行数计数"""
        self._line_count = 0
    
    def set_scroll_boundary(self, max_lines: int) -> None:
        """设置滚动边界"""
        self._max_scroll_lines = max_lines


class SmartInputBox:
    """
    智能固定输入框
    
    采用分层策略：
    1. 首选：ANSI滚动区域（如果终端支持）
    2. 备选：输出行数跟踪 + 主动滚动
    3. 降级：普通输入行 + 提示符
    """
    
    def __init__(self):
        self.info = TerminalDetector.detect()
        self.output = SafeOutput(self.info)
        self._active = False
        self._height = 0
        self._width = 0
        self._strategy = None
        self._border_char = "─"
        self._last_resize_check = 0
        
        # 选择策略
        self._select_strategy()
        
        print(f"[TerminalFrame] Detected: {self.info.name} ({self.info.width}x{self.info.height})")
        print(f"[TerminalFrame] Strategy: {self._strategy.__name__ if self._strategy else 'none'}")
    
    def _select_strategy(self) -> None:
        """根据终端能力选择策略"""
        if self.info.supports_scroll_region and self.info.height >= 10:
            self._strategy = self._strategy_scroll_region
        elif self.info.height >= 8:
            self._strategy = self._strategy_line_tracking
        else:
            self._strategy = self._strategy_basic
    
    def _strategy_scroll_region(self, action: str) -> None:
        """ANSI滚动区域策略"""
        if action == "setup":
            # 设置滚动区域：第1行到第height-3行
            self.output.write(f"\033[1;{self._height-3}r")
            self._draw_borders()
            self.output.write(f"\033[{self._height-3};1H")
            self.output.set_scroll_boundary(self._height - 3)
            
        elif action == "before_input":
            self._check_resize()
            self._draw_borders()  # 每次输入前重绘边框
            self.output.write(f"\033[{self._height-1};1H\033[2K")
            
        elif action == "after_input":
            self.output.write(f"\033[{self._height-1};1H\033[2K")  # 清空输入行
            # 重绘下边框（可能被输入覆盖）
            bottom_border = "-" * self._width
            self.output.write(f"\033[{self._height};1H\033[2K{bottom_border}")
            self.output.write(f"\033[{self._height-3};1H")  # 光标回滚区域
            
        elif action == "ensure_position":
            self.output.write(f"\033[{self._height-3};1H")
            
        elif action == "teardown":
            self.output.write("\033[r")  # 重置滚动区域
            self._clear_borders()
    
    def _strategy_line_tracking(self, action: str) -> None:
        """行数跟踪策略（无滚动区域）"""
        if action == "setup":
            # 绘制初始边框
            self._draw_borders()
            # 光标定位到输入区域上方
            self.output.write(f"\033[{self._height-3};1H")
            self.output.set_scroll_boundary(self._height - 4)
            
        elif action == "before_input":
            self._check_resize()
            # 清除可能的覆盖，重绘边框
            self._draw_borders()
            # 定位到输入行
            self.output.write(f"\033[{self._height-1};1H\033[2K")
            
        elif action == "after_input":
            # 清空输入行，光标回到内容区域
            self.output.write(f"\033[{self._height-1};1H\033[2K")
            # 重绘下边框（可能被输入覆盖）
            bottom_border = "-" * self._width
            self.output.write(f"\033[{self._height};1H\033[2K{bottom_border}")
            self.output.write(f"\033[{self._height-3};1H")
            
        elif action == "ensure_position":
            # 确保在内容区域
            self.output.write(f"\033[{self._height-3};1H")
            
        elif action == "teardown":
            self._clear_borders()
    
    def _strategy_basic(self, action: str) -> None:
        """基础策略（终端太小或不支持高级功能）"""
        if action == "setup":
            print("\n" * 2)  # 预留空间
            
        elif action == "before_input":
            sys.stdout.write('> ')
            sys.stdout.flush()
            
        elif action == "after_input":
            print()  # 换行
            
        elif action == "ensure_position":
            pass  # 基础策略无位置保证
            
        elif action == "teardown":
            pass
    
    def _draw_borders(self) -> None:
        """绘制边框"""
        if self._strategy in [self._strategy_scroll_region, self._strategy_line_tracking]:
            # 使用ASCII字符确保兼容性
            top_border_char = "="  # 双线替代
            bottom_border_char = "-"  # 单线替代
            top_border = top_border_char * self._width
            bottom_border = bottom_border_char * self._width
            
            # 上边框（第height-2行）
            self.output.write(f"\033[{self._height-2};1H\033[2K{top_border}")
            # 输入行（清空）（第height-1行）
            self.output.write(f"\033[{self._height-1};1H\033[2K")
            # 下边框（第height行）
            self.output.write(f"\033[{self._height};1H\033[2K{bottom_border}")
    
    def _clear_borders(self) -> None:
        """清除边框"""
        if self._strategy in [self._strategy_scroll_region, self._strategy_line_tracking]:
            self.output.write(f"\033[{self._height-2};1H\033[2K")
            self.output.write(f"\033[{self._height-1};1H\033[2K")
            self.output.write(f"\033[{self._height};1H\033[2K")
    
    def _check_resize(self) -> None:
        """检查终端尺寸变化"""
        current_time = time.time()
        if current_time - self._last_resize_check < 0.1:  # 100ms防抖
            return
        
        self._last_resize_check = current_time
        
        try:
            size = shutil.get_terminal_size()
            new_height, new_width = size.lines, size.columns
            
            if (new_height, new_width) != (self._height, self._width):
                self._height, self._width = new_height, new_width
                # 重新选择策略
                self.info.height, self.info.width = new_height, new_width
                self._select_strategy()
                # 重新设置
                if self._active:
                    self._strategy("teardown")
                    self._strategy("setup")
        except:
            pass
    
    # 公开接口
    def setup(self) -> bool:
        """初始化输入框"""
        try:
            size = shutil.get_terminal_size()
            self._height, self._width = size.lines, size.columns
            
            if self._height < 6:
                print(f"[TerminalFrame] Terminal too small ({self._height} lines), using basic mode")
                self._strategy = self._strategy_basic
            
            self._strategy("setup")
            self._active = True
            return True
        except Exception as e:
                print(f"[TerminalFrame] Initialization failed: {e}")
                self._strategy = self._strategy_basic
                self._strategy("setup")
                self._active = True
                return False
    
    def before_input(self) -> None:
        """输入前准备"""
        if not self._active:
            return
        self._strategy("before_input")
    
    def after_input(self) -> None:
        """输入后清理"""
        if not self._active:
            return
        self._strategy("after_input")
    
    def ensure_output_position(self) -> None:
        """确保输出位置正确"""
        if not self._active:
            return
        self._strategy("ensure_position")
    
    def teardown(self) -> None:
        """清理资源"""
        if not self._active:
            return
        self._strategy("teardown")
        self._active = False
    
    def safe_print(self, text: str) -> None:
        """安全打印（自动定位）"""
        self.ensure_output_position()
        self.output.write(text)
    
    def get_input_line_position(self) -> Tuple[int, int]:
        """获取输入行位置（行，列）"""
        return (self._height - 1, 1) if self._active else (self._height, 1)
    
    # 兼容性方法 - 用于 ds.py 的 _FixedInputBox 接口
    def before_read(self) -> None:
        """输入前准备 (兼容 _FixedInputBox.before_read)"""
        self.before_input()
    
    def after_read(self) -> None:
        """输入后清理 (兼容 _FixedInputBox.after_read)"""
        self.after_input()
    
    def ensure_scroll_position(self) -> None:
        """确保滚动位置正确 (兼容 _FixedInputBox.ensure_scroll_position)"""
        self.ensure_output_position()


# 全局实例
_input_box = None

def get_input_box() -> SmartInputBox:
    """获取全局输入框实例"""
    global _input_box
    if _input_box is None:
        _input_box = SmartInputBox()
    return _input_box


if __name__ == "__main__":
    # 测试代码
    print("终端输入框框架测试")
    box = SmartInputBox()
    
    if box.setup():
        print("✅ 输入框初始化成功")
        
        # 测试输出
        box.safe_print("这是一条测试输出\\n")
        box.safe_print("另一条输出\\n")
        
        # 模拟输入
        box.before_input()
        print("（模拟输入：Hello World）")
        box.after_input()
        
        box.safe_print("输入完成后的输出\\n")
        
        box.teardown()
        print("✅ 测试完成")
    else:
        print("❌ 输入框初始化失败")