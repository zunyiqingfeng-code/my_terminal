#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ds_input.py — DS Terminal 独立键盘输入库  v1.1
================================================
专为 DeepSeek Terminal 设计，启动时 import 即激活。

功能
----
  ✓ Shift+Enter / Ctrl+J  → 换行（不提交）
  ✓ Enter                 → 提交
  ✓ Esc                   → 中断/暂停（替代Ctrl+C）
  ✓ 多行粘贴               → 括号粘贴模式，整块插入不中途触发提交
  ✓ 鼠标滚轮 / 文本选择    → 终端原生处理（mouse_support=False）
  ✓ ↑ / ↓ 浏览历史
  ✓ prompt_toolkit 不可用时自动降级到 input()

关键设计决策
-----------
  mouse_support=False
    prompt_toolkit 开启后会拦截所有鼠标事件（用于点击定位光标），
    导致：① 滚轮无法滚动终端历史；② 拖拽无法选中文本。
    False = 完全交给终端原生处理，两个需求都满足。

  multiline=True + eager Enter
    multiline=True 让缓冲区支持 \n 并正确渲染多行。
    默认 multiline 行为是 Enter→换行、Meta+Enter→提交，与需求相反。
    用 eager=True 的 Enter 绑定覆盖默认，实现反转：
      Enter       = 提交
      Shift+Enter = 换行

  括号粘贴（Bracketed Paste Mode）
    prompt_toolkit 3.x 的 VT100 输入层自动启用，无需额外配置。
    粘贴含换行的代码/文本时，整块被 ESC[200~ … ESC[201~ 包裹，
    输入层将其视为一次性文本而非逐键事件，不会中途触发 Enter。

  Esc键中断机制
    用户按Esc键触发EscInterrupt异常（KeyboardInterrupt子类），替代原来的Ctrl+C。
    在Agent思考过程中，Esc键可用于随时中断思考流程。

Shift+Enter 转义序列（逐字符绑定）
-----------------------------------
  各终端对 Shift+Enter 发送不同的 VT 序列，全部逐字符注册：
    ESC [ 1 3 ; 2 u      Windows Terminal ≥ 1.18 / kitty / foot
    ESC [ 2 7 ; 2 ; 1 3 ~ VTE (GNOME Terminal) / xterm modifyOtherKeys=2
    ESC enter            Alt+Enter 通用兼容（escape + enter）
    ESC O M              xterm application-keypad Shift+KP_Enter
  Ctrl+J（ASCII LF）作为终极备选，任何终端均可用。

用法
----
    from ds_input import create_input_session
    from pathlib import Path

    session = create_input_session(Path("~/.ds_prompt_history"))
    try:
        text = session.read("> ")
    except (EOFError, KeyboardInterrupt):
        ...
"""

from __future__ import annotations

import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 可选依赖
# ──────────────────────────────────────────────────────────────────────────────
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

# ESC键中断异常（KeyboardInterrupt子类）
class EscInterrupt(KeyboardInterrupt):
    """ESC键触发的中断异常"""
    def __init__(self, message: str = "用户按ESC键中断"):
        super().__init__(message)
        self.timestamp = __import__('time').time()
        self.message = message
    
    def __str__(self):
        return f"{self.message} (at {self.timestamp})"

_PROMPT_STYLE = Style.from_dict({"prompt": "#00aaff bold"}) if _HAS_PT else None

# 配置选项
class DSInputConfig:
    """DS输入系统配置"""
    def __init__(self):
        # 错误处理
        self.verbose_errors = False  # 详细错误信息
        self.fallback_to_input = True  # 降级到input()
        
        # 中断功能
        self.enable_esc_interrupt = True  # 启用ESC中断
        
        # 样式配置
        self.prompt_style = {"prompt": "#00aaff bold"}  # 提示样式
        self.prompt_text = "> "  # 默认提示文本
        
        # 键盘绑定配置
        self.key_bindings = {
            "enter": "submit",  # "submit"或"newline"
            "shift_enter": "newline",
            "ctrl_j": "newline",
            "escape": "interrupt",
        }
        
        # 历史记录配置
        self.history_size = 1000  # 历史记录条数
        self.enable_history_search = True  # 启用历史搜索
        
        # 性能配置
        self.enable_caching = True  # 启用缓存
        self.mouse_support = False  # 鼠标支持（false=终端原生处理）
        
        # 多行输入配置
        self.multiline = True  # 启用多行输入
        self.complete_while_typing = False  # 输入时自动补全
        self.complete_in_thread = True  # 在线程中补全
    
    @classmethod
    def default(cls):
        return cls()
    
    def update(self, **kwargs):
        """更新配置并清除缓存（如果需要）"""
        cache_invalidated = False
        for key, value in kwargs.items():
            if hasattr(self, key):
                old_value = getattr(self, key)
                setattr(self, key, value)
                # 如果配置更改影响缓存，标记为无效
                if key in ["enable_esc_interrupt", "key_bindings", "prompt_style"]:
                    if old_value != value:
                        cache_invalidated = True
        
        if cache_invalidated:
            global _KEY_BINDINGS_CACHE
            _KEY_BINDINGS_CACHE = None

# 全局配置实例
_CONFIG = DSInputConfig.default()

# Shift+Enter：各终端的 VT 转义序列，拆成 prompt_toolkit 接受的逐字符元组
_SHIFT_ENTER_BINDINGS: tuple[tuple[str, ...], ...] = (
    ("escape", "[", "1", "3", ";", "2", "u"),                   # Win Terminal / kitty
    ("escape", "[", "2", "7", ";", "2", ";", "1", "3", "~"),    # VTE / GNOME
    ("escape", "enter"),                                          # Alt+Enter 通用
    ("escape", "O", "M"),                                         # xterm app-keypad
)


# ──────────────────────────────────────────────────────────────────────────────
# 键盘绑定
# ──────────────────────────────────────────────────────────────────────────────

# 缓存键盘绑定实例
_KEY_BINDINGS_CACHE = None

def _build_key_bindings() -> "KeyBindings":
    """
    构建键盘绑定表。

    eager=True 确保我们的绑定优先于 prompt_toolkit 内置的
    multiline Enter（换行）绑定，实现 Enter=提交 的语义反转。
    """
    global _KEY_BINDINGS_CACHE
    if _KEY_BINDINGS_CACHE is not None:
        return _KEY_BINDINGS_CACHE
    
    kb = KeyBindings()

    @kb.add("enter", eager=True)
    def _enter(event) -> None:
        """Enter：提交缓冲区内容。"""
        event.current_buffer.validate_and_handle()

    for _seq in _SHIFT_ENTER_BINDINGS:
        @kb.add(*_seq, eager=True)
        def _newline(event) -> None:
            """Shift+Enter（各变体）：插入换行，不提交。"""
            event.current_buffer.insert_text("\n")

    @kb.add("c-j", eager=True)
    def _ctrl_j(event) -> None:
        """Ctrl+J (ASCII LF)：最通用的换行备选，任何终端均可用。"""
        event.current_buffer.insert_text("\n")

    # Esc键：暂停/中断（替换原来的Ctrl+C）
    if _CONFIG.enable_esc_interrupt:
        @kb.add("escape", eager=True)
        def _esc_key(event) -> None:
            """Esc键：触发EscInterrupt中断agent思考。"""
            # 通过触发app.exit()来抛出EscInterrupt
            from prompt_toolkit.application import get_app
            app = event.app
            # 获取当前缓冲区内容（如果有）
            buffer_text = event.current_buffer.text
            preview = buffer_text[:50] + ("..." if len(buffer_text) > 50 else "")
            msg = f"ESC键中断 (输入预览: {repr(preview)})"
            event.app.exit(exception=EscInterrupt(msg))
    
    _KEY_BINDINGS_CACHE = kb
    return kb


# ──────────────────────────────────────────────────────────────────────────────
# 输入会话
# ──────────────────────────────────────────────────────────────────────────────

class DSInputSession:
    """DS Terminal 输入会话，封装 PromptSession 对外只暴露 .read()。"""

    def __init__(self, history_path: Path | None = None) -> None:
        self._history_path = history_path
        self._session: "PromptSession | None" = None
        if _HAS_PT:
            self._init_session()

    def _init_session(self) -> None:
        history = (
            FileHistory(str(self._history_path.expanduser()))
            if self._history_path
            else InMemoryHistory()
        )
        # 使用配置样式
        style = Style.from_dict(_CONFIG.prompt_style) if _HAS_PT else None
        self._session = PromptSession(
            history=history,
            style=style,
            key_bindings=_build_key_bindings(),

            # 使用配置选项
            multiline=_CONFIG.multiline,
            mouse_support=_CONFIG.mouse_support,
            complete_while_typing=_CONFIG.complete_while_typing,
            enable_history_search=_CONFIG.enable_history_search,
            complete_in_thread=_CONFIG.complete_in_thread,
            
            # 固定配置（通常不需要修改）
            include_default_pygments_style=False,
            enable_system_prompt=False,
            enable_open_in_editor=False,
        )

    def read(self, prompt_text: str = "> ") -> str:
        """
        读取用户输入。

          Enter         → 提交，返回字符串（可含内嵌 \n）
          Shift+Enter   → 换行，继续编辑
          Ctrl+J        → 换行（跨终端备选）
          Esc           → 中断/暂停（触发KeyboardInterrupt）
          粘贴多行       → 整块插入，Enter 后一次提交
          ↑ / ↓         → 浏览历史
          鼠标滚轮       → 终端原生（不被拦截）
          鼠标选中       → 终端原生（不被拦截）

        抛出 EOFError / KeyboardInterrupt 由调用方处理。
        """
        if self._session is None:
            if not _CONFIG.fallback_to_input:
                raise RuntimeError("prompt_toolkit不可用且未启用降级到input()")
            if _CONFIG.verbose_errors and not _HAS_PT:
                import sys
                print(f"[ds_input警告] prompt_toolkit不可用，降级到input()", file=sys.stderr)
            return input(prompt_text)
        try:
            text = self._session.prompt(prompt_text)
            # multiline 模式末尾可能附带多余 \n，统一去掉
            if text and text.endswith('\n'):
                return text.rstrip("\n")
            return text if text is not None else ""
        except Exception as e:
            if _CONFIG.verbose_errors:
                import sys
                print(f"[ds_input错误] 输入会话异常: {e}", file=sys.stderr)
            # 如果是KeyboardInterrupt或EOFError，直接抛出
            if isinstance(e, (KeyboardInterrupt, EOFError)):
                raise
            # 其他异常尝试降级到input()
            if _CONFIG.fallback_to_input:
                if _CONFIG.verbose_errors:
                    print(f"[ds_input] 降级到input()", file=sys.stderr)
                return input(prompt_text)
            raise

    @property
    def available(self) -> bool:
        """prompt_toolkit 是否成功初始化。"""
        return self._session is not None


# ──────────────────────────────────────────────────────────────────────────────
# 工厂函数（推荐入口）
# ──────────────────────────────────────────────────────────────────────────────

def create_input_session(
    history_path: "Path | str | None" = None,
    config: "DSInputConfig | None" = None,
) -> DSInputSession:
    """
    创建并返回 DSInputSession。

    Args:
        history_path: 历史记录文件路径，None=内存历史，str 自动转 Path，
                      支持 ~ 展开（如 "~/.ds_prompt_history"）。
        config: 配置对象，None=使用默认配置。

    Returns:
        DSInputSession 实例，调用 .read("> ") 即可。
    """
    if isinstance(history_path, str):
        history_path = Path(history_path)
    # 使用提供的配置或默认配置
    global _CONFIG, _KEY_BINDINGS_CACHE
    if config is not None:
        # 如果配置有变化，清除键盘绑定缓存
        if _CONFIG is not config:
            _KEY_BINDINGS_CACHE = None
        _CONFIG = config
    return DSInputSession(history_path=history_path)


# ──────────────────────────────────────────────────────────────────────────────
# 内置自测（python ds_input.py）
# ──────────────────────────────────────────────────────────────────────────────

def _self_test() -> int:
    """静态自测，不需要用户交互。返回失败数（0=全部通过）。"""
    P = "\033[32m[OK]\033[0m"
    F = "\033[31m[FAIL]\033[0m"
    results: list[tuple[bool, str]] = []

    def check(name: str, ok: bool) -> None:
        results.append((ok, name))
        print(f"  {P if ok else F} {name}")

    print("\n── ds_input 自测 ────────────────────────────────────")

    # T1 依赖
    check("prompt_toolkit 可用", _HAS_PT)

    # T2 工厂函数
    sess: DSInputSession | None = None
    try:
        sess = create_input_session()
        check("create_input_session() 无异常", True)
    except Exception as e:
        check(f"create_input_session() [{e}]", False)
        _summary(results)
        return sum(1 for ok, _ in results if not ok)

    # T3 接口
    check(".available 属性存在", hasattr(sess, "available"))
    check(".read() 可调用",      callable(getattr(sess, "read", None)))

    # T4 PromptSession 配置
    if sess._session is not None:
        s = sess._session
        check("mouse_support=False          （原生滚轮/选中）", not s.mouse_support)
        check("multiline=True               （缓冲区支持换行）", bool(s.multiline))
        check("enable_history_search=True   （↑↓历史）",
              bool(getattr(s, "enable_history_search", False)))
    else:
        check("PromptSession 配置（已降级 input()）", True)

    # T5 键盘绑定
    if _HAS_PT:
        kb = _build_key_bindings()
        n  = len(kb.bindings)
        exp = 1 + len(_SHIFT_ENTER_BINDINGS) + 1 + 1  # enter + shifts + c-j + escape
        check(f"key_bindings >= {exp} 个   (实际 {n} 个)", n >= exp)

        from prompt_toolkit.keys import Keys
        from prompt_toolkit.filters.base import Always
        enter_b = [b for b in kb.bindings
                   if hasattr(b, "keys") and b.keys == (Keys.ControlM,)]
        check("Enter 绑定存在 (Keys.ControlM)", bool(enter_b))
        if enter_b:
            check("Enter 绑定 eager=True   （覆盖默认换行）",
                  enter_b[0].eager())

    # T6 history_path 类型处理
    import tempfile
    for label, hp in [
        ("str history_path",  str(Path("/tmp/ds_test_hist_str"))),
        ("Path history_path", Path("/tmp/ds_test_hist_path")),
        ("None history_path", None),
    ]:
        try:
            create_input_session(history_path=hp)
            check(f"{label} 正常", True)
        except Exception as e:
            check(f"{label} [{e}]", False)

    _summary(results)
    return sum(1 for ok, _ in results if not ok)


def _summary(results: list[tuple[bool, str]]) -> None:
    passed = sum(1 for ok, _ in results if ok)
    total  = len(results)
    print(f"\n结果: {passed}/{total}", end="  ")
    if passed == total:
        print("\033[32m全部通过\033[0m")
    else:
        print(f"\033[31m失败: {[n for ok, n in results if not ok]}\033[0m")
    print("─────────────────────────────────────────────────────")


if __name__ == "__main__":
    fail = _self_test()
    if "--interactive" in sys.argv:
        print("\n── 交互测试 ──────────────────────────────────────────")
        print("  Enter=提交  Shift+Enter/Ctrl+J=换行  Esc=中断  Ctrl+C/D退出\n")
        sess = create_input_session()
        while True:
            try:
                t = sess.read("[ds]> ")
                lines = t.splitlines() if t else []
                print(f"  → {len(lines)} 行: {repr(t)}")
            except (EOFError, KeyboardInterrupt):
                print("\n退出")
                break
    sys.exit(fail)
