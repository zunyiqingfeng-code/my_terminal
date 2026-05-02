#!/usr/bin/env python


# ===== 延迟加载模块 =====
_lazy_modules = {}

def _lazy_import(module_name):
    """延迟导入模块"""
    if module_name not in _lazy_modules:
        import importlib
        _lazy_modules[module_name] = importlib.import_module(module_name)
    return _lazy_modules[module_name]

def get_lazy_module(module_name):
    """获取延迟加载的模块"""
    return _lazy_import(module_name)
# -*- coding: utf-8 -*-
"""
ds.py — DeepSeek Terminal
极简暗色  ·  工具调用  ·  长期记忆

用法:  python ds.py
记忆:  ~/.ds_memory/   (Markdown 文件 + MEMORY.md 索引)
"""

import os
import re
import sys
import json
import time
import threading
import base64
import mimetypes
import subprocess
import traceback
import io
from PIL import Image
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from ds_input import EscInterrupt
except ImportError:
    # ds_input可能不可用，定义回退类
    class EscInterrupt(KeyboardInterrupt):
        pass

# ESC键全局检测辅助函数
def check_esc_key_pressed() -> bool:
    """
    检查ESC键是否被按下（非阻塞）。
    返回True如果ESC键被按下，否则False。
    仅支持Windows（msvcrt），其他平台返回False。
    """
    try:
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            # ESC键的编码是 b'\x1b'
            if ch == b'\x1b':
                # 检查是否还有后续字符（可能是一个转义序列的开始）
                # 如果是单独的ESC键，返回True
                # 如果后面还有字符，可能是其他转义序列，放回缓冲区
                if not msvcrt.kbhit():
                    return True
                else:
                    # 将ESC键放回缓冲区
                    msvcrt.ungetch(ch)
            else:
                # 将字符放回缓冲区
                msvcrt.ungetch(ch)
    except (ImportError, OSError):
        # 非Windows平台或msvcrt不可用
        pass
    return False



# 本地模型工具（Ollama）
# Local model tools (Ollama) — set OLLAMA_MODELS_PATH if needed
# sys.path.insert(0, os.environ.get("OLLAMA_MODELS_PATH", ""))
try:
    from ds_local_model import list_local_models as _list_local_models, chat_local as _chat_local
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False

# SolidWorks 工具
try:
    from ds_solidworks_tool import (
        tool_solidworks_connect,
        tool_solidworks_disconnect,
        tool_solidworks_info,
        tool_solidworks_create_part,
        tool_solidworks_open_file,
        tool_solidworks_create_gear,
        tool_solidworks_batch,
        tool_solidworks_test,
        tool_solidworks_help,
    )
    pass
except ImportError:
    pass


# 强制 stdin/stdout 使用 UTF-8，避免 Windows GBK 编码导致 surrogate 错误
if sys.stdin and hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, datetime

# ===== view_image 性能统计 =====
_view_image_stats = {"total": 0, "success": 0, "failures": 0, "total_time": 0.0}
_view_image_stats_lock = threading.Lock()
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from rich.table import Table
import rich.box

# ===== 终端输入框框架 =====
try:
    from terminal_frame import get_input_box, SmartInputBox
    TERMINAL_FRAME_AVAILABLE = True
except ImportError as e:
    TERMINAL_FRAME_AVAILABLE = False

from prompt_toolkit import PromptSession
from prompt_toolkit.clipboard import Clipboard
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory

# ===== 键盘操作库导入 =====
try:
    from keyboard_library import get_keyboard_library, create_enhanced_session, enable_keyboard_features, get_keyboard_status
    KEYBOARD_LIB_AVAILABLE = True
except ImportError:
    KEYBOARD_LIB_AVAILABLE = False

# ===== Vision Analyzer 技能导入 =====
try:
    vision_analyzer_path = Path.home() / ".claude" / "skills" / "vision-analyzer" / "scripts"
    if str(vision_analyzer_path) not in sys.path:
        sys.path.insert(0, str(vision_analyzer_path))
    from vision_helper import (
        analyze_image, tool_view_image, get_stats, test_connection
    )
    VISION_ANALYZER_AVAILABLE = True
except ImportError:
    VISION_ANALYZER_AVAILABLE = False

# ===== 配置 =====

# ===== MCP Server 配置 =====
MCP_SERVER_CONFIG = {
    "enabled": True,
    "port": 3000,
    "max_workers": 5,       # 弹性上限
    "scale_threshold": 3,   # 并发>此值时扩容
    "idle_timeout": 60,     # 空闲N秒回收多余实例
}
# ===== 网络监控（默认关闭，/netmon 手动开启） =====
NETWORK_MONITOR_ENABLED = False   # 启动时不自动开
_NETWORK_MONITOR_AVAILABLE = False
try:
    from simple_network_monitor import (
        get_network_monitor,
        start_network_monitoring,
        stop_network_monitoring,
        get_network_status,
        get_network_details
    )
    _NETWORK_MONITOR_AVAILABLE = True
except ImportError:
    def get_network_status():
        return "❓ 网络监控未安装"
    def get_network_details():
        return "网络监控模块未加载"
    def start_network_monitoring():
        pass
    def stop_network_monitoring():
        pass


# MCP Server 集群实例
_mcp_cluster = None

def start_mcp_server():
    """启动 MCP Server 弹性池（1实例起步，按需扩容）"""
    global _mcp_cluster
    if not MCP_SERVER_CONFIG["enabled"]:
        return False
    try:
        from ds_mcp_improved_framework import MCPServerConfig, MCPServerPool
        config = MCPServerConfig(
            enabled=True,
            port=MCP_SERVER_CONFIG["port"],
            max_workers=MCP_SERVER_CONFIG["max_workers"],
            scale_threshold=MCP_SERVER_CONFIG["scale_threshold"],
            idle_timeout=MCP_SERVER_CONFIG["idle_timeout"],
        )
        _mcp_cluster = MCPServerPool(config)
        return _mcp_cluster.start()
    except Exception:
        return False

def stop_mcp_server():
    """停止 MCP Server"""
    global _mcp_cluster
    if _mcp_cluster:
        _mcp_cluster.stop()
        _mcp_cluster = None

def get_mcp_server_stats():
    """获取 MCP Server 统计信息"""
    global _mcp_cluster
    if _mcp_cluster:
        return _mcp_cluster.get_stats()
    return {"running": False, "message": "MCP Server 未运行"}

API_KEY      = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL     = "https://api.deepseek.com"
MODELS       = {"chat": "deepseek-v4-flash", "r1": "deepseek-v4-flash"}

# 视觉模型（Qwen-VL via 阿里云百炼国内版）—— 为 DeepSeek 提供"眼睛"
VISION_API_KEY  = os.environ.get("VISION_API_KEY", "")
VISION_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VISION_MODEL    = "qwen-vl-plus"   # 换成 "qwen-vl-max" 可获得更强识别效果

HISTORY_PATH = Path.home() / ".ds_history"
PYTHON_BIN   = os.environ.get("PYTHON_BIN", sys.executable)
MEMORY_DIR   = Path.home() / ".ds_memory"
SESSION_DIR  = Path.home() / ".ds_sessions"
LIVE_DIR     = Path.home() / ".ds_live"      # 在线实例注册目录

_session_name: str = ""     # 当前实例名（/name 命令或 --name 参数设置）
_inbox_read_pos: int = 0    # 已展示的收件箱行数（防重复提醒）


# ===== 智能API连接修复 =====
# 解决国内API连接问题，确保国内外都能连上

import requests
import time
import socket
from typing import Optional, Dict, Tuple

class EnhancedAPIFixer:
    import requests
    """增强的API连接管理器，解决连接不稳定问题"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        # 设置NO_PROXY环境变量，确保DeepSeek API不走代理
        no_proxy = os.environ.get('NO_PROXY', '')
        if 'deepseek.com' not in no_proxy:
            os.environ['NO_PROXY'] = f'{no_proxy},deepseek.com,api.deepseek.com'.strip(',')
            os.environ['no_proxy'] = os.environ['NO_PROXY']
        
        self.endpoints = [
            {"name": "global", "url": "https://api.deepseek.com", "priority": 1},
            {"name": "proxy", "url": "https://api.deepseek.com", "priority": 2},
        ]
        self.current_endpoint = None
        self.proxy_url = None
        self.client = None
        self.last_check_time = 0
        self.check_interval = 60  # 每1分钟检查一次连接
        self.connection_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "last_error": None,
            "last_success": None
        }
        
        # 启动后台健康检查线程
        self.health_check_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        self.health_check_thread.start()
        
        # 初始化连接
        self._detect_proxy()
        self._select_best_endpoint()
        self._create_client()
    
    def _detect_proxy(self):
        """检测可用代理"""
        proxy_ports = [7889, 7897, 10808, 7890, 7891, 10809, 1080, 1087]
        
        for port in proxy_ports:
            proxy_url = f"http://127.0.0.1:{port}"
            try:
                test_response = requests.get(
                    "http://httpbin.org/ip",
                    proxies={"http": proxy_url, "https": proxy_url},
                    timeout=3.0
                )
                if test_response.status_code == 200:
                    self.proxy_url = proxy_url
                    print(f"[API] 找到代理: {proxy_url}")
                    break
            except:
                continue
    
    def _test_endpoint(self, endpoint: dict) -> Tuple[bool, float]:
        """测试端点连接性"""
        url = f"{endpoint['url']}/v1/models"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        proxies = None
        if endpoint["name"] == "proxy" and self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}
        
        try:
            start_time = time.time()
            response = requests.get(
                url,
                headers=headers,
                timeout=10,
                proxies=proxies
            )
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                return True, elapsed
            else:
                return False, elapsed
                
        except Exception as e:
            return False, 0
    
    def _select_best_endpoint(self):
        """选择最佳API端点"""
        print("[API] 检测最佳连接方式...")
        
        # 先测试直接连接
        direct_endpoint = self.endpoints[0]
        success, response_time = self._test_endpoint(direct_endpoint)
        
        if success:
            self.current_endpoint = direct_endpoint
            print(f"[API] ✅ 直接连接成功: {response_time:.2f}秒")
            return
        
        # 直接连接失败，尝试代理
        if self.proxy_url:
            proxy_endpoint = self.endpoints[1]
            success, response_time = self._test_endpoint(proxy_endpoint)
            
            if success:
                self.current_endpoint = proxy_endpoint
                print(f"[API] ✅ 代理连接成功: {response_time:.2f}秒")
                return
        
        # 所有连接都失败，使用直接连接作为默认
        self.current_endpoint = direct_endpoint
        print("[API] ⚠️ 所有连接测试失败，使用默认端点")
    
    def _create_client(self):
        import httpx
        """创建HTTP客户端"""
        from openai import OpenAI
        
        if not self.current_endpoint:
            self._select_best_endpoint()
        
        # 优化HTTP客户端配置
        http_client_kwargs = {
            "timeout": 120.0,  # 增加超时时间到120秒，特别是对于图片处理
            "limits": httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=60.0  # 增加keepalive时间
            ),
            "http2": True,  # 启用HTTP/2
            "follow_redirects": True,  # 跟随重定向
            "trust_env": True,  # 信任环境变量（HTTP_PROXY/HTTPS_PROXY/NO_PROXY）
        }
        
        # 如果是代理端点，设置代理
        if self.current_endpoint["name"] == "proxy" and self.proxy_url:
            http_client_kwargs["proxies"] = self.proxy_url
        
        # 创建HTTP客户端
        http_client = httpx.Client(**http_client_kwargs)
        
        # 创建OpenAI客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.current_endpoint["url"],
            http_client=http_client,
            timeout=60.0,
            max_retries=5  # 增加重试次数
        )
    
    def _health_check_loop(self):
        """后台健康检查循环"""
        while True:
            try:
                time.sleep(self.check_interval)
                self._check_connection_health()
            except:
                pass
    
    def _check_connection_health(self):
        """检查连接健康状态"""
        try:
            start_time = time.time()
            models = self.get_client().models.list()
            elapsed = time.time() - start_time
            
            if elapsed < 5.0:  # 响应时间小于5秒为健康
                self.connection_stats["last_success"] = time.time()
                print(f"[API] 健康检查: 连接正常 ({elapsed:.2f}秒)")
            else:
                print(f"[API] 健康检查: 连接较慢 ({elapsed:.2f}秒)")
                
        except Exception as e:
            self.connection_stats["last_error"] = str(e)
            print(f"[API] 健康检查: 连接失败 - {e}")
            # 尝试重新连接
            self._reconnect()
    
    def _reconnect(self):
        """重新连接API"""
        print("[API] 尝试重新连接...")
        # 重新检测代理，确保代理状态变化时能正确切换
        self._detect_proxy()
        self._select_best_endpoint()
        self._create_client()
    
    def get_client(self):
        """获取客户端，如果连接失败则尝试重新连接"""
        if not self.client:
            self._create_client()
        
        # 如果最近有错误，检查连接
        if self.connection_stats["last_error"]:
            current_time = time.time()
            if current_time - self.last_check_time > 60:  # 至少1分钟检查一次
                self._check_connection_health()
                self.last_check_time = current_time
        
        return self.client
    
    def get_status(self) -> str:
        """获取连接状态"""
        if not self.current_endpoint:
            return "未初始化"
        
        status = f"当前端点: {self.current_endpoint['name']} ({self.current_endpoint['url']})"
        if self.current_endpoint["name"] == "proxy" and self.proxy_url:
            status += f" [代理: {self.proxy_url}]"
        
        # 添加统计信息
        success_rate = 0
        if self.connection_stats["total_requests"] > 0:
            success_rate = (self.connection_stats["successful_requests"] / 
                          self.connection_stats["total_requests"]) * 100
        
        status += f"\n请求统计: {self.connection_stats['successful_requests']}/{self.connection_stats['total_requests']} 成功 ({success_rate:.1f}%)"
        
        return status
    
    def record_request(self, success: bool):
        """记录请求结果"""
        self.connection_stats["total_requests"] += 1
        if success:
            self.connection_stats["successful_requests"] += 1
        else:
            self.connection_stats["failed_requests"] += 1

# ===== 消息历史修复器 =====

class MessageHistoryFixer:
    """修复消息历史格式问题"""
    
    @staticmethod
    def fix_message_sequence(messages):
        """
        修复消息序列，确保tool消息正确对应tool_calls
        解决: "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
        """
        if not messages:
            return messages
        
        fixed_messages = []
        pending_tool_calls = {}  # 记录未完成的tool_calls
        
        for i, msg in enumerate(messages):
            role = msg.get("role")
            
            if role == "assistant":
                # 检查是否有tool_calls
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    # 记录这些tool_calls需要对应的tool消息
                    for tc in tool_calls:
                        tc_id = tc.get("id")
                        if tc_id:
                            pending_tool_calls[tc_id] = {
                                "assistant_index": len(fixed_messages),
                                "tool_call": tc
                            }
                    fixed_messages.append(msg)
                else:
                    fixed_messages.append(msg)
                    
            elif role == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id in pending_tool_calls:
                    # 这是对应的tool消息
                    del pending_tool_calls[tc_id]
                    fixed_messages.append(msg)
                else:
                    # 这是孤立的tool消息，需要移除
                    print(f"[消息修复] 移除孤立的tool消息: tool_call_id={tc_id}")
                    
            else:  # user, system
                # 新的用户消息或系统消息会清除所有pending的tool_calls
                if role in ("user", "system") and pending_tool_calls:
                    print(f"[消息修复] 清除{len(pending_tool_calls)}个未完成的tool_calls")
                    # 移除对应的assistant消息
                    indices_to_remove = set()
                    for tc_info in pending_tool_calls.values():
                        indices_to_remove.add(tc_info["assistant_index"])
                    
                    # 反向移除，避免索引问题
                    for idx in sorted(indices_to_remove, reverse=True):
                        if idx < len(fixed_messages):
                            print(f"[消息修复] 移除未完成的assistant消息 (索引{idx})")
                            fixed_messages.pop(idx)
                    
                    pending_tool_calls.clear()
                
                fixed_messages.append(msg)
        
        # 如果还有未完成的tool_calls，移除对应的assistant消息
        if pending_tool_calls:
            print(f"[消息修复] 会话结束，清除{len(pending_tool_calls)}个未完成的tool_calls")
            indices_to_remove = set()
            for tc_info in pending_tool_calls.values():
                indices_to_remove.add(tc_info["assistant_index"])
            
            for idx in sorted(indices_to_remove, reverse=True):
                if idx < len(fixed_messages):
                    print(f"[消息修复] 移除未完成的assistant消息 (索引{idx})")
                    fixed_messages.pop(idx)
        
        return fixed_messages
    
    @staticmethod
    def validate_message_format(messages):
        """验证消息格式是否正确"""
        if not messages:
            return True
        
        pending_tool_calls = set()
        
        for msg in messages:
            role = msg.get("role")
            
            if role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    tc_id = tc.get("id")
                    if tc_id:
                        pending_tool_calls.add(tc_id)
                        
            elif role == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id in pending_tool_calls:
                    pending_tool_calls.remove(tc_id)
                else:
                    print(f"[验证失败] 孤立的tool消息: {tc_id}")
                    return False
        
        if pending_tool_calls:
            print(f"[验证失败] 未完成的tool_calls: {pending_tool_calls}")
            return False
        
        return True



# ===== API 客户端（主备切换：DeepSeek ↔ Ollama） =====

_OLLAMA_BASE = "http://localhost:11434/v1"
_OLLAMA_MODEL = "qwen3:8b-16k"

class _APIRouter:
    """管理 DeepSeek（主）和 Ollama（备）之间的自动切换"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._ds_client = None       # DeepSeek 客户端
        self._ollama_client = None   # Ollama 备用客户端
        self._api_fixer = None
        self._using_fallback = False  # 当前是否在用 Ollama
        self._fail_count = 0         # DeepSeek 连续失败次数
        self._fail_threshold = 2     # 连续失败 N 次后降级
        self._last_ds_try = 0.0      # 上次尝试回切 DeepSeek 的时间
        self._ds_retry_interval = 120  # 降级后每 120s 尝试回切

    def _init_deepseek(self):
        if self._ds_client:
            return
        try:
            from enhanced_api_fixer import EnhancedAPIFixer as _ExtFixer
            self._api_fixer = _ExtFixer(self.api_key)
        except ImportError:
            self._api_fixer = EnhancedAPIFixer(self.api_key)
        self._ds_client = self._api_fixer.get_client()

    def _init_ollama(self):
        if self._ollama_client:
            return
        from openai import OpenAI
        self._ollama_client = OpenAI(
            api_key="ollama",
            base_url=_OLLAMA_BASE,
            timeout=30.0,
            max_retries=1,
        )

    @property
    def client(self):
        """返回当前活跃的客户端"""
        if self._using_fallback:
            # 定期尝试回切 DeepSeek
            if time.time() - self._last_ds_try > self._ds_retry_interval:
                if self._probe_deepseek():
                    self._using_fallback = False
                    self._fail_count = 0
                self._last_ds_try = time.time()
            self._init_ollama()
            return self._ollama_client
        self._init_deepseek()
        return self._ds_client

    @property
    def current_model(self) -> str:
        """返回当前应使用的模型名"""
        if self._using_fallback:
            return _OLLAMA_MODEL
        return ""  # 空串表示用调用方指定的模型

    def record_success(self):
        """API 调用成功"""
        self._fail_count = 0
        if self._using_fallback:
            pass  # Ollama 成功不切回，等 _probe 切

    def record_failure(self):
        """API 调用失败，累计计数，达到阈值自动降级"""
        self._fail_count += 1
        if self._fail_count >= self._fail_threshold and not self._using_fallback:
            self._using_fallback = True
            self._last_ds_try = time.time()
            try:
                self._init_ollama()
                # 快速探测 Ollama 是否可用
                self._ollama_client.models.list()
            except Exception:
                # Ollama 也不可用，回退到 DeepSeek（总比没有好）
                self._using_fallback = False

    def _probe_deepseek(self) -> bool:
        """快速探测 DeepSeek 是否恢复"""
        try:
            self._init_deepseek()
            import urllib.request
            req = urllib.request.Request(
                f"{BASE_URL}/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False

    @property
    def is_fallback(self) -> bool:
        return self._using_fallback

    @property
    def api_fixer(self):
        self._init_deepseek()
        return self._api_fixer


_api_router = _APIRouter(API_KEY)

def get_client():
    """获取当前活跃的 API 客户端（DeepSeek 或 Ollama）"""
    return _api_router.client

def get_api_fixer():
    return _api_router.api_fixer

# 向后兼容
client = None
api_fixer = None
def _init_global_client():
    global client, api_fixer
    if client is None:
        client = get_client()
    if api_fixer is None:
        api_fixer = get_api_fixer()
    return client

console = Console(highlight=False)

# UI颜色常量
_LB = "#44ccff"  # Light Blue - 浅蓝色
_DB = "#0066cc"  # Dark Blue - 深蓝色


# ===== 长期记忆系统 =====

import json
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, Optional

# ===== 工具缓存系统 =====

# ===== 本地计算引擎（减少token使用）=====

class LocalComputeEngine:
    """本地计算引擎，将更多处理转移到本地以减少API调用"""
    
    def __init__(self):
        self.cpu_count = os.cpu_count() or 4
        self.max_workers = min(self.cpu_count * 2, 16)  # 充分利用CPU
        self.local_cache = {}
        self.cache_ttl = 3600  # 1小时
        self.local_models = {}
        
        pass  # 静默初始化
    
    def text_summarization(self, text: str, max_length: int = 200) -> str:
        """本地文本摘要算法（替代API摘要）"""
        if not text or len(text) < 50:
            return text
        
        # 缓存检查
        cache_key = f"summary_{hash(text)}_{max_length}"
        if cache_key in self.local_cache:
            cached = self.local_cache[cache_key]
            if time.time() - cached['timestamp'] < self.cache_ttl:
                return cached['result']
        
        try:
            # 基于规则的摘要算法
            sentences = re.split(r'[。！？.!?]', text)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            if len(sentences) <= 3:
                result = text[:max_length]
            else:
                # 提取关键句子（基于长度、位置、关键词）
                scored_sentences = []
                for i, sentence in enumerate(sentences):
                    score = 0
                    
                    # 位置权重：开头和结尾更重要
                    if i < 3:  # 开头
                        score += 2
                    elif i > len(sentences) - 4:  # 结尾
                        score += 1.5
                    
                    # 长度权重：中等长度的句子更好
                    sentence_len = len(sentence)
                    if 20 <= sentence_len <= 100:
                        score += 1
                    
                    # 关键词权重（简单实现）
                    important_words = {"重要", "关键", "总结", "主要", "核心", "结论", "因此", "所以", "但是", "然而"}
                    for word in important_words:
                        if word in sentence:
                            score += 0.5
                    
                    scored_sentences.append((score, sentence))
                
                # 选择得分最高的句子
                scored_sentences.sort(reverse=True)
                selected = scored_sentences[:min(5, len(scored_sentences))]
                selected_sentences = [s[1] for s in selected]
                selected_sentences.sort(key=lambda x: sentences.index(x))  # 恢复原始顺序
                
                result = "。".join(selected_sentences) + "。"
                if len(result) > max_length:
                    result = result[:max_length] + "..."
            
            # 缓存结果
            self.local_cache[cache_key] = {
                'result': result,
                'timestamp': time.time()
            }
            
            return result
            
        except Exception as e:
            print(f"[dim]⚠️ 本地摘要失败: {e}[/]")
            return text[:max_length]
    
    def text_classification(self, text: str) -> dict:
        """本地文本分类（判断任务类型）"""
        # 简单的基于关键词的分类
        categories = {
            "code": ["代码", "编程", "python", "java", "c++", "函数", "类", "变量", "import", "def"],
            "file": ["文件", "读取", "写入", "目录", "路径", "创建", "删除", "移动", "复制"],
            "search": ["搜索", "查找", "查询", "百度", "谷歌", "bing", "网页"],
            "system": ["系统", "命令", "执行", "运行", "进程", "内存", "cpu", "磁盘"],
            "data": ["数据", "处理", "分析", "统计", "表格", "csv", "excel", "json"],
            "question": ["什么", "为什么", "如何", "怎么", "?", "？", "请教", "请问"]
        }
        
        text_lower = text.lower()
        scores = {cat: 0 for cat in categories}
        
        for category, keywords in categories.items():
            for keyword in keywords:
                if keyword in text_lower:
                    scores[category] += 1
        
        # 归一化分数
        total = sum(scores.values())
        if total > 0:
            for cat in scores:
                scores[cat] = scores[cat] / total
        
        return scores
    
    def context_compression_local(self, messages: list, keep_recent: int = 20) -> list:
        """本地上下文压缩（完全替代API压缩）"""
        if len(messages) <= keep_recent + 1:
            return messages
        
        system_msg = messages[0]
        old_msgs = messages[1:-(keep_recent)]
        recent_msgs = messages[-(keep_recent):]
        
        to_compress = [
            m for m in old_msgs
            if m["role"] in ("user", "assistant") and m.get("content", "").strip()
        ]
        
        if not to_compress:
            return messages
        
        # 构建对话文本
        dialogue = "".join([
            f"{'用户' if m['role'] == 'user' else 'DS'}: {m['content'][:2000]}"
            for m in to_compress
        ])
        
        # 使用本地摘要
        summary = self.text_summarization(dialogue, max_length=300)
        
        compressed = {"role": "system", "content": f"[本地摘要] {summary}"}
        print(f"[dim]🗜  本地压缩 {len(to_compress)} 条旧消息[/]")
        
        return [system_msg, compressed] + list(recent_msgs)
    
    def parallel_local_processing(self, tasks: list, task_func) -> list:
        """并行本地处理"""
        if len(tasks) <= 1:
            return [task_func(task) for task in tasks]
        
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(task_func, task): i for i, task in enumerate(tasks)}
            for future in as_completed(futures):
                try:
                    results.append((futures[future], future.result()))
                except Exception as e:
                    results.append((futures[future], f"错误: {e}"))
        
        # 按原始顺序排序
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results]
    
    def optimize_system_prompt_local(self, base_prompt: str, task_type: str = None) -> str:
        """本地优化系统提示"""
        # 根据任务类型精简提示
        if task_type == "simple":
            # 简单任务：只保留核心功能
            lines = base_prompt.split('\n')
            keep_sections = ["你是 DS", "工具能力", "上下文"]
            filtered = []
            in_keep_section = False
            
            for line in lines:
                if any(section in line for section in keep_sections):
                    in_keep_section = True
                elif line.strip().startswith("---"):
                    in_keep_section = False
                
                if in_keep_section or not line.strip():
                    filtered.append(line)
            
            return ''.join(filtered)
        
        return base_prompt
    
    def estimate_token_savings(self, original_length: int, processed_length: int) -> dict:
        """估计token节省量"""
        savings = original_length - processed_length
        savings_percent = (savings / original_length * 100) if original_length > 0 else 0
        
        return {
            "original_tokens": original_length // 4,  # 粗略估计：1 token ≈ 4字符
            "processed_tokens": processed_length // 4,
            "saved_tokens": savings // 4,
            "savings_percent": savings_percent,
            "efficiency": "高" if savings_percent > 30 else "中" if savings_percent > 10 else "低"
        }

# 全局本地计算引擎
_local_engine = LocalComputeEngine()

# ===== 性能监控 =====

class PerformanceMonitor:
    """性能监控和优化"""
    
    def __init__(self):
        self.tool_times = {}  # 工具执行时间统计
        self.api_times = []   # API响应时间统计
        self.start_time = time.time()
        self.max_records = 50
    
    def local_text_analysis(self, text: str) -> dict:
        """本地文本分析（替代部分API分析）"""
        analysis = {
            "length": len(text),
            "word_count": len(text.split()),
            "sentence_count": len(re.split(r'[。！？.!?]', text)),
            "contains_code": any(keyword in text.lower() for keyword in ["def ", "class ", "import ", "function ", "var ", "const "]),
            "contains_question": any(keyword in text for keyword in ["?", "？", "什么", "如何", "为什么", "怎么"]),
            "complexity": "高" if len(text) > 500 else "中" if len(text) > 100 else "低"
        }
        
        # 简单的情绪分析（基于关键词）
        positive_words = ["好", "成功", "完成", "正确", "优秀", "感谢", "谢谢", "很好", "完美"]
        negative_words = ["错误", "失败", "问题", "bug", "错误", "不好", "糟糕", "麻烦"]
        
        analysis["positive_score"] = sum(1 for word in positive_words if word in text)
        analysis["negative_score"] = sum(1 for word in negative_words if word in text)
        analysis["sentiment"] = "积极" if analysis["positive_score"] > analysis["negative_score"] else "消极" if analysis["negative_score"] > analysis["positive_score"] else "中性"
        
        return analysis
    
    def local_response_generation(self, query: str, context: dict = None) -> str:
        """本地响应生成（用于简单查询）"""
        # 常见问题的本地响应
        local_responses = {
            "你好": "你好！我是DS，有什么可以帮助你的吗？",
            "谢谢": "不客气！很高兴能帮到你。",
            "再见": "再见！期待下次为你服务。",
            "时间": f"当前时间是：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "日期": f"今天是：{date.today().isoformat()}",
            "帮助": "我可以帮你执行命令、读写文件、搜索信息等。请告诉我你需要什么帮助。",
            "版本": "DS Terminal v1.0，基于DeepSeek API构建。",
            "状态": "系统运行正常，所有工具可用。",
        }
        
        query_lower = query.lower().strip()
        for pattern, response in local_responses.items():
            if pattern in query_lower:
                return response
        
        # 系统命令相关
        if any(cmd in query_lower for cmd in ["列出文件", "查看目录", "list dir"]):
            return "我可以使用list_dir工具帮你列出目录内容。"
        
        if any(cmd in query_lower for cmd in ["读取文件", "read file", "打开文件"]):
            return "我可以使用read_file工具帮你读取文件内容。"
        
        if any(cmd in query_lower for cmd in ["搜索", "search", "查找"]):
            return "我可以使用web_search工具帮你搜索信息。"
        
        # 如果没有匹配的本地响应，返回None表示需要API处理
        return None
    
    def optimize_messages_local(self, messages: list) -> list:
        """本地优化消息列表（减少token）"""
        optimized = []
        
        for msg in messages:
            if msg["role"] == "system":
                # 简化系统消息
                content = msg["content"]
                if len(content) > 1000:
                    # 截断过长的系统消息
                    content = content[:1000] + "...\n[内容已截断]"
                optimized.append({"role": "system", "content": content})
            
            elif msg["role"] in ("user", "assistant"):
                content = msg["content"]
                
                # 移除多余的空行和空格
                content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
                content = re.sub(r'[ \t]+', ' ', content)
                
                # 如果内容过长，尝试本地摘要
                if len(content) > 500:
                    summary = _local_engine.text_summarization(content, max_length=300)
                    if len(summary) < len(content) * 0.7:  # 如果摘要显著更短
                        content = f"{summary}\n[详细内容已摘要]"
                
                optimized.append({"role": msg["role"], "content": content.strip()})
            
            else:
                optimized.append(msg)
        
        # 计算优化效果
        original_len = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        optimized_len = sum(len(json.dumps(m, ensure_ascii=False)) for m in optimized)
        
        if optimized_len < original_len:
            savings = _local_engine.estimate_token_savings(original_len, optimized_len)
            print(f"[dim]🔧 消息优化: 节省{savings['saved_tokens']} tokens[/]")
        
        return optimized
    
    def should_use_local(self, query: str, context_size: int) -> bool:
        """判断是否应该使用本地处理"""
        # 简单查询使用本地
        if len(query) < 50:
            return True
        
        # 常见问题使用本地
        common_patterns = ["你好", "谢谢", "再见", "时间", "日期", "帮助", "版本", "状态"]
        if any(pattern in query for pattern in common_patterns):
            return True
        
        # 上下文过大时优先本地
        if context_size > 3000:  # token估计
            return True
        
        # 本地响应生成测试
        local_response = self.local_response_generation(query)
        if local_response is not None:
            return True
        
        return False
    
    def process_locally_first(self, query: str, context: list) -> dict:
        """优先本地处理策略"""
        result = {
            "processed_locally": False,
            "local_response": None,
            "optimized_context": context,
            "token_savings": 0
        }
        
        # 1. 尝试本地响应生成
        local_response = self.local_response_generation(query)
        if local_response is not None:
            result["processed_locally"] = True
            result["local_response"] = local_response
            print(f"[dim]🔧 本地响应生成[/]")
            return result
        
        # 2. 优化上下文（减少token）
        optimized_context = self.optimize_messages_local(context)
        if optimized_context != context:
            result["optimized_context"] = optimized_context
            
            # 计算节省的token
            original_len = sum(len(json.dumps(m, ensure_ascii=False)) for m in context)
            optimized_len = sum(len(json.dumps(m, ensure_ascii=False)) for m in optimized_context)
            savings = _local_engine.estimate_token_savings(original_len, optimized_len)
            result["token_savings"] = savings["saved_tokens"]
            
            print(f"[dim]🔧 上下文优化: 节省{savings['saved_tokens']} tokens[/]")
        
        # 3. 文本分析（用于决策）
        analysis = self.local_text_analysis(query)
        if analysis["complexity"] == "低" and not analysis["contains_code"]:
            result["processed_locally"] = self.should_use_local(query, len(json.dumps(context)))
        
        return result

    def record_tool_time(self, tool_name: str, execution_time: float):
        """记录工具执行时间"""
        if tool_name not in self.tool_times:
            self.tool_times[tool_name] = []
        
        self.tool_times[tool_name].append(execution_time)
        
        # 保持记录数量
        if len(self.tool_times[tool_name]) > self.max_records:
            self.tool_times[tool_name] = self.tool_times[tool_name][-self.max_records:]
    
    def record_api_time(self, response_time: float):
        """记录API响应时间"""
        self.api_times.append(response_time)
        
        # 保持记录数量
        if len(self.api_times) > self.max_records:
            self.api_times = self.api_times[-self.max_records:]
    
    def get_tool_stats(self, tool_name: str = None) -> dict:
        """获取工具性能统计"""
        if tool_name:
            if tool_name not in self.tool_times or not self.tool_times[tool_name]:
                return {"count": 0, "avg_time": 0, "min_time": 0, "max_time": 0}
            
            times = self.tool_times[tool_name]
            return {
                "count": len(times),
                "avg_time": sum(times) / len(times),
                "min_time": min(times),
                "max_time": max(times)
            }
        else:
            # 所有工具统计
            all_stats = {}
            for name, times in self.tool_times.items():
                if times:
                    all_stats[name] = {
                        "count": len(times),
                        "avg_time": sum(times) / len(times),
                        "min_time": min(times),
                        "max_time": max(times)
                    }
            return all_stats
    
    def get_api_stats(self) -> dict:
        """获取API性能统计"""
        if not self.api_times:
            return {"count": 0, "avg_time": 0, "min_time": 0, "max_time": 0}
        
        return {
            "count": len(self.api_times),
            "avg_time": sum(self.api_times) / len(self.api_times),
            "min_time": min(self.api_times),
            "max_time": max(self.api_times)
        }
    
    def get_slow_tools(self, threshold: float = 2.0) -> list:
        """获取执行缓慢的工具（超过阈值秒）"""
        slow_tools = []
        for name, times in self.tool_times.items():
            if times and sum(times) / len(times) > threshold:
                slow_tools.append({
                    "name": name,
                    "avg_time": sum(times) / len(times),
                    "count": len(times)
                })
        
        # 按平均时间排序
        slow_tools.sort(key=lambda x: x["avg_time"], reverse=True)
        return slow_tools
    
    def get_optimization_suggestions(self) -> list:
        """获取性能优化建议"""
        suggestions = []
        
        # 检查缓慢的工具
        slow_tools = self.get_slow_tools()
        for tool in slow_tools[:3]:  # 只显示前3个最慢的工具
            suggestions.append(f"工具 '{tool['name']}' 执行较慢（平均{tool['avg_time']:.1f}秒），考虑优化")
        
        # 检查API响应时间
        api_stats = self.get_api_stats()
        if api_stats["count"] >= 3 and api_stats["avg_time"] > 5.0:
            suggestions.append(f"API响应较慢（平均{api_stats['avg_time']:.1f}秒），考虑调整模型或网络")
        
        # 检查工具调用频率
        total_tool_calls = sum(len(times) for times in self.tool_times.values())
        if total_tool_calls > 20:
            # 找出最常调用的工具
            frequent_tools = []
            for name, times in self.tool_times.items():
                if times and len(times) >= 5:
                    frequent_tools.append({
                        "name": name,
                        "count": len(times),
                        "avg_time": sum(times) / len(times)
                    })
            
            frequent_tools.sort(key=lambda x: x["count"], reverse=True)
            for tool in frequent_tools[:2]:
                if tool["count"] > 10:
                    suggestions.append(f"工具 '{tool['name']}' 调用频繁（{tool['count']}次），考虑批量处理或缓存")
        
        return suggestions
    
    def get_session_summary(self) -> dict:
        """获取会话性能摘要"""
        uptime = time.time() - self.start_time
        
        return {
            "uptime_seconds": uptime,
            "uptime_formatted": f"{int(uptime // 3600)}小时{int((uptime % 3600) // 60)}分钟{int(uptime % 60)}秒",
            "total_tool_calls": sum(len(times) for times in self.tool_times.values()),
            "total_api_calls": len(self.api_times),
            "unique_tools": len(self.tool_times),
            "slow_tools": len(self.get_slow_tools()),
            "optimization_suggestions": self.get_optimization_suggestions()
        }

# 全局性能监控器
_perf_monitor = PerformanceMonitor()

# ===== Token 使用统计和预测 =====

class TokenTracker:
    """Token使用统计和预测"""
    
    def __init__(self):
        self.session_tokens = {
            "prompt": 0,
            "completion": 0,
            "total": 0
        }
        self.history = []  # 保存最近N次调用的token使用情况
        self.max_history = 20
    
    def add_usage(self, prompt_tokens: int, completion_tokens: int):
        """记录一次API调用的token使用"""
        self.session_tokens["prompt"] += prompt_tokens
        self.session_tokens["completion"] += completion_tokens
        self.session_tokens["total"] += prompt_tokens + completion_tokens
        
        # 添加到历史记录
        self.history.append({
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
            "timestamp": time.time()
        })
        
        # 保持历史记录长度
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
    
    def get_session_stats(self) -> dict:
        """获取当前会话统计"""
        return self.session_tokens.copy()
    
    def get_average_usage(self) -> dict:
        """获取平均token使用情况"""
        if not self.history:
            return {"prompt": 0, "completion": 0, "total": 0}
        
        avg_prompt = sum(h["prompt"] for h in self.history) / len(self.history)
        avg_completion = sum(h["completion"] for h in self.history) / len(self.history)
        avg_total = sum(h["total"] for h in self.history) / len(self.history)
        
        return {
            "prompt": int(avg_prompt),
            "completion": int(avg_completion),
            "total": int(avg_total)
        }
    
    def predict_next_usage(self, context_length: int) -> dict:
        """预测下一次API调用的token使用"""
        avg = self.get_average_usage()
        
        # 基于上下文长度调整预测
        context_factor = min(1.0, context_length / 4000)  # 假设最大上下文为4000
        
        predicted_prompt = int(avg["prompt"] * (1 + context_factor * 0.5))
        predicted_completion = int(avg["completion"] * (1 + context_factor * 0.3))
        
        return {
            "predicted_prompt": predicted_prompt,
            "predicted_completion": predicted_completion,
            "predicted_total": predicted_prompt + predicted_completion,
            "confidence": 0.7 if len(self.history) >= 5 else 0.3  # 置信度
        }
    
    def get_optimization_suggestions(self) -> list:
        """获取优化建议"""
        suggestions = []
        avg = self.get_average_usage()
        
        if avg["prompt"] > 2000:
            suggestions.append("提示词过长，考虑压缩系统提示或记忆")
        
        if avg["completion"] > 1000:
            suggestions.append("回复过长，考虑更简洁的回答")
        
        if avg["total"] > 3000:
            suggestions.append("总token使用较高，考虑优化对话流程")
        
        if len(self.history) >= 3 and avg["prompt"] / avg["total"] > 0.8:
            suggestions.append("提示词占比过高，考虑减少不必要的上下文")
        
        return suggestions
    
    def reset_session(self):
        """重置会话统计"""
        self.session_tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.history = []

# 全局token跟踪器
_token_tracker = TokenTracker()

# ===== 工具缓存系统 =====

class ToolCache:
    """工具结果缓存系统"""
    
    def __init__(self, cache_dir: Optional[Path] = None, ttl: int = 3600):
        """
        初始化缓存系统
        :param cache_dir: 缓存目录，默认 ~/.ds_memory/cache/
        :param ttl: 缓存有效期（秒），默认1小时
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".ds_memory" / "cache"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
    
    def _get_cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """生成缓存键"""
        # 将参数转换为可哈希的字符串
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
        key_data = f"{tool_name}:{args_str}"
        return hashlib.md5(key_data.encode('utf-8')).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"
    
    def get(self, tool_name: str, args: Dict[str, Any]) -> Optional[str]:
        """获取缓存结果"""
        cache_key = self._get_cache_key(tool_name, args)
        cache_path = self._get_cache_path(cache_key)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 检查缓存是否过期
            if time.time() - cache_data.get('timestamp', 0) > self.ttl:
                cache_path.unlink(missing_ok=True)
                return None
            
            return cache_data.get('result')
        except Exception:
            # 缓存文件损坏，删除它
            cache_path.unlink(missing_ok=True)
            return None
    
    def set(self, tool_name: str, args: Dict[str, Any], result: str):
        """设置缓存结果"""
        cache_key = self._get_cache_key(tool_name, args)
        cache_path = self._get_cache_path(cache_key)
        
        cache_data = {
            'tool_name': tool_name,
            'args': args,
            'result': result,
            'timestamp': time.time()
        }
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # 缓存写入失败，忽略
    
    def clear(self):
        """清空缓存"""
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
            except Exception:
                pass

# 全局缓存实例
_tool_cache = ToolCache()

# 需要缓存的工具列表
_CACHEABLE_TOOLS = {
    "read_file",    # 文件读取（文件内容不变时）
    "list_dir",     # 目录列表（目录内容不变时）
    "glob_files",   # 文件搜索（模式不变时）
    "grep_files",   # 文件搜索（模式不变时）
    "session_list", # 会话列表
    "session_recv", # 收件箱读取
}

def _safe_call_with_cache(fn, args: dict, name: str) -> str:
    """带缓存的工具调用（增强参数验证）"""
    if not fn:
        return f"[unknown tool: {name}]"
    
    # 参数验证：确保 args 是字典
    if not isinstance(args, dict):
        return f"[error] {name}(): 参数必须是字典，实际是 {type(args).__name__}"

    # 注意：session_list / task_complete 等工具允许空 args，不在此拦截
    
    # 检查是否需要缓存
    if name in _CACHEABLE_TOOLS:
        # 尝试从缓存获取
        cached_result = _tool_cache.get(name, args)
        if cached_result is not None:
            return f"[cached] {cached_result}"
    
    # 工具超时配置（秒）
    timeout_config = {
        "shell": 300,          # 5分钟
        "python_exec": 60,     # 1分钟
        "web_search": 30,      # 30秒
        "fetch_url": 30,       # 30秒
        "view_image": 60,      # 1分钟
        "default": 30,         # 默认30秒
    }
    
    timeout = timeout_config.get(name, timeout_config["default"])
    
    try:
        # 使用线程实现超时
        import threading
        result = []
        exception = []
        
        def worker():
            try:
                # 在调用前验证函数签名
                import inspect
                sig = inspect.signature(fn)
                required_params = []
                
                # 检查必需参数
                for param_name, param in sig.parameters.items():
                    if param.default == inspect.Parameter.empty and param_name != "self":
                        required_params.append(param_name)
                
                # 验证必需参数是否存在
                missing_params = [p for p in required_params if p not in args]
                if missing_params:
                    raise TypeError(f"缺少必需参数: {', '.join(missing_params)}")
                
                result.append(fn(**args))
            except Exception as e:
                exception.append(e)
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            return f"[timeout] {name}(): 执行超时 ({timeout}秒)"
        
        if exception:
            raise exception[0]
        
        tool_result = result[0] if result else ""
        
        # 缓存结果
        if name in _CACHEABLE_TOOLS:
            _tool_cache.set(name, args, tool_result)
        
        return tool_result
        
    except Exception as e:
        return f"[error] {name}(): {e}"

def _init_memory():
    """初始化记忆目录和索引"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    index = MEMORY_DIR / "MEMORY.md"
    if not index.exists():
        index.write_text(
            "# Memory Index\n\n## User\n\n## Feedback\n\n## Project\n\n## Reference\n",
            encoding="utf-8"
        )

# ===== 多实例协作系统 =====

def session_register(name: str) -> None:
    """注册当前实例到 LIVE_DIR/<name>/info.json"""
    global _session_name
    if _session_name and _session_name != name:
        session_deregister()
    _session_name = name
    d = LIVE_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "inbox.jsonl").touch()
    info = {
        "name": name,
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    (d / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

def session_deregister() -> None:
    """注销当前实例（退出时调用）"""
    global _session_name
    if _session_name:
        info_path = LIVE_DIR / _session_name / "info.json"
        if info_path.exists():
            info_path.unlink()
        _session_name = ""

def _session_pid_alive(pid: int) -> bool:
    """检查 Windows 进程是否存在"""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=3
        )
        return str(pid) in r.stdout
    except Exception:
        return False

def _check_inbox_notify() -> None:
    """检查收件箱新消息并打印提醒（非侵入式，每次输入前调用）"""
    global _inbox_read_pos
    if not _session_name:
        return
    inbox_path = LIVE_DIR / _session_name / "inbox.jsonl"
    if not inbox_path.exists():
        return
    lines = inbox_path.read_text(encoding="utf-8").splitlines()
    new_lines = [l for l in lines[_inbox_read_pos:] if l.strip()]
    if not new_lines:
        return
    console.print(f"\n[bold cyan]╔══ 📬 新消息 ({len(new_lines)} 条) ══╗[/]")
    for line in new_lines:
        try:
            m = json.loads(line)
            console.print(f"[cyan]║  {m.get('ts','')}  来自 [bold]{m.get('from','?')}[/bold][/]")
            console.print(f"[cyan]║  {m.get('message','')}[/]")
        except Exception:
            pass
    console.print("[bold cyan]╚═══════════════════════╝[/]\n")
    _inbox_read_pos = len(lines)  # 统一用原始行数做游标

def load_memories() -> str:
    """智能加载记忆：根据当前上下文只加载相关记忆"""
    _init_memory()
    if not MEMORY_DIR.exists():
        return ""
    
    index = MEMORY_DIR / "MEMORY.md"
    try:
        index_content = index.read_text(encoding="utf-8")
    except Exception:
        return ""
    
    # 解析索引，获取所有记忆文件信息
    memory_files = []
    current_section = ""
    
    for line in index_content.splitlines():
        line = line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
        elif line.startswith("- ["):
            # 解析格式: - [名称](文件名.md) — 描述
            import re
            match = re.match(r'- \[([^\]]+)\]\(([^)]+)\) — (.+)', line)
            if match:
                name, filename, description = match.groups()
                memory_files.append({
                    "section": current_section,
                    "name": name,
                    "filename": filename,
                    "description": description
                })
    
    # 默认加载所有记忆（后续可添加智能筛选逻辑）
    # 这里可以添加基于当前任务类型的智能筛选
    # 例如：如果用户询问技术问题，优先加载技术相关记忆
    
    sections = [f"""# 长期记忆（跨会话持久）

## 索引
{index_content}

## 详细内容
"""]
    
    # 加载所有记忆文件（后续可优化为只加载相关文件）
    loaded_count = 0
    for mem_info in memory_files:
        f = MEMORY_DIR / mem_info["filename"]
        if f.exists():
            try:
                content_text = f.read_text(encoding="utf-8")
                # 只加载前2000字符，避免token过多
                if len(content_text) > 2000:
                    content_text = content_text[:2000] + "...\n[内容已截断]"
                sections.append(f"""### [{mem_info['name']}]
{content_text}
""")
                loaded_count += 1
            except Exception:
                pass
    
    # 添加加载统计
    if loaded_count > 0:
        sections.append(f"\n[已加载 {loaded_count} 个记忆文件]")
    
    return "\n".join(sections)
def _update_index(filename: str, name: str, description: str, mem_type: str):
    """更新 MEMORY.md 索引条目"""
    index = MEMORY_DIR / "MEMORY.md"
    content = index.read_text(encoding="utf-8")
    entry = f"- [{name}]({filename}) — {description}"

    # 删除旧条目（如果存在）
    lines = [l for l in content.split("\n") if f"({filename})" not in l]

    # 找对应 section 并插入
    section_map = {
        "user": "## User", "feedback": "## Feedback",
        "project": "## Project", "reference": "## Reference",
    }
    target = section_map.get(mem_type, "## Other")

    # 若 section 不存在则追加
    if target not in "\n".join(lines):
        lines.append(f"\n{target}")

    result, inserted = [], False
    for line in lines:
        result.append(line)
        if line.strip() == target and not inserted:
            result.append(entry)
            inserted = True
    if not inserted:
        result.append(entry)

    index.write_text("\n".join(result), encoding="utf-8")

def save_memory(filename: str, name: str, description: str,
                mem_type: str, content: str):
    """写入记忆文件并更新索引"""
    _init_memory()
    path = MEMORY_DIR / filename
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{content}\n",
        encoding="utf-8"
    )
    _update_index(filename, name, description, mem_type)
    console.print(f"[dim cyan]💾 记忆已保存: {filename}[/]")
    _sp_cache["dirty"] = True           # 记忆变化 → 下轮重建系统提示

def delete_memory(filename: str):
    """删除记忆文件"""
    path = MEMORY_DIR / filename
    if path.exists():
        path.unlink()
        # 从索引中移除
        index = MEMORY_DIR / "MEMORY.md"
        content = index.read_text(encoding="utf-8")
        lines = [l for l in content.split("\n") if f"({filename})" not in l]
        index.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"[dim red]🗑  记忆已删除: {filename}[/]")
        _sp_cache["dirty"] = True       # 记忆变化 → 下轮重建系统提示

def extract_think_blocks(text: str) -> tuple:
    """提取 <THINK> 标签，返回 (clean_text, [thoughts])"""
    pattern = re.compile(r"<THINK>(.*?)</THINK>", re.DOTALL)
    thoughts = [t.strip() for t in pattern.findall(text)]
    clean = pattern.sub("", text).strip()
    return clean, thoughts

def extract_and_save_memories(text: str) -> str:
    """
    从 AI 回复中解析 <MEMORY_UPDATE> 标签，保存记忆并返回干净文本。
    支持多条记忆。
    """
    pattern = re.compile(r"<MEMORY_UPDATE>(.*?)</MEMORY_UPDATE>", re.DOTALL)
    matches = pattern.findall(text)

    for block in matches:
        data = {}
        content_lines = []
        in_content = False
        for line in block.strip().split("\n"):
            if in_content:
                content_lines.append(line)
            elif line.startswith("content:"):
                in_content = True
                rest = line[len("content:"):].strip()
                if rest:
                    content_lines.append(rest)
            elif ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
        if content_lines:
            data["content"] = "\n".join(content_lines)

        if "file" not in data:
            continue

        action = data.get("action", "create")
        if action == "delete":
            delete_memory(data["file"])
        else:
            save_memory(
                filename    = data["file"],
                name        = data.get("name", data["file"]),
                description = data.get("description", ""),
                mem_type    = data.get("type", "project"),
                content     = data.get("content", ""),
            )

    # 返回去掉标签的干净文本
    clean = pattern.sub("", text).strip()
    return clean

def show_memories():
    """打印当前所有记忆（供 /memory 命令使用）"""
    _init_memory()
    console.print("[cyan]--- 长期记忆 ---[/]")
    console.print(Panel(
        load_memories(),
        title="[cyan]长期记忆[/]",
        border_style="cyan",
    ))
# ===== 跨会话持久化 =====

def save_session(messages: list):
    """退出时将当前会话保存到 ~/.ds_sessions/YYYY-MM-DD_HH-MM-SS.json"""
    to_save = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in messages
        if m["role"] in ("user", "assistant") and m.get("content", "").strip()
    ]
    if len(to_save) < 2:
        return  # 太短不保存
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = SESSION_DIR / f"{ts}.json"
    path.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[dim]💾 会话已保存: {path.name}[/]")

def load_last_session_context(n_turns: int = 5) -> str:
    """读取最近一次会话的最后 n_turns 轮，返回注入系统提示的字符串"""
    if not SESSION_DIR.exists():
        return ""
    sessions = sorted(SESSION_DIR.glob("*.json"), reverse=True)
    if not sessions:
        return ""
    last = sessions[0]
    try:
        msgs = json.loads(last.read_text(encoding="utf-8"))
        recent = msgs[-(n_turns * 2):]
        if not recent:
            return ""
        date_str = last.stem[:10]  # "2026-03-28"
        lines = [f"# 上次会话片段（{date_str}）\n"]
        for m in recent:
            role = "DS" if m["role"] == "assistant" else "用户"
            content = m["content"]
            if len(content) > 600:
                content = content[:600] + "…（已截断）"
            lines.append(f"**{role}**: {content}\n")
        return "\n".join(lines)
    except Exception:
        return ""

def generate_and_save_session_summary(messages: list, model_name: str):
    """退出时调 API 生成结构化摘要，存为记忆文件，供下次会话直接使用"""
    to_summarize = [
        m for m in messages
        if m["role"] in ("user", "assistant") and m.get("content", "").strip()
    ]
    if len(to_summarize) < 2:
        return  # 太短无意义
    sample = to_summarize[-40:]  # 最多取40条
    dialogue = "\n".join([
        f"{'用户' if m['role'] == 'user' else 'DS'}: {m['content'][:500]}"
        for m in sample
    ])
    today = date.today().isoformat()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        resp = get_client().chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是精准摘要助手，只输出结构化摘要，不解释、不客套。"},
                {"role": "user", "content": f"""用中文严格按以下格式总结对话，每项不超过3行：

## 会话摘要（{today}）

**主题：** [1-5个关键词]

**完成的任务：**
- （列出已完成的具体任务）

**重要决策/发现：**
- （用户做了哪些决策，发现了哪些重要信息）

**项目进度：**
- （涉及的项目当前状态）

**待续：**
- （未完成或下次需要继续的事项，无则填"无"）

---
对话：
{dialogue}"""},
            ],
            stream=False,
        )
        summary = resp.choices[0].message.content.strip()
        save_memory(
            filename=f"session_{today}.md",
            name=f"会话摘要 {today}",
            description=f"{today} 会话自动摘要：{summary[:60]}",
            mem_type="project",
            content=summary,
        )
        console.print(f"[dim cyan]📝 会话摘要已保存至记忆[/]")
    except Exception as e:
        console.print(f"[dim]摘要生成失败: {e}[/]")

def compress_context(messages: list, model_name: str, keep_recent: int = 40) -> list:
    """长会话中压缩旧消息：优先使用本地计算引擎"""
    # 首先尝试本地压缩
    try:
        local_result = _local_engine.context_compression_local(messages, keep_recent)
        if local_result != messages:
            return local_result
    except Exception as e:
        print(f"[dim]⚠️ 本地压缩失败，回退到API: {e}[/]")
    
    # 本地压缩失败或无效，回退到原有逻辑
    if len(messages) <= keep_recent + 1:
        return messages
    system_msg = messages[0]
    old_msgs = messages[1:-(keep_recent)]
    recent_msgs = messages[-(keep_recent):]
    to_compress = [
        m for m in old_msgs
        if m["role"] in ("user", "assistant") and m.get("content", "").strip()
    ]
    if not to_compress:
        return messages
    
    dialogue = "\n".join([
        f"{'用户' if m['role'] == 'user' else 'DS'}: {m['content'][:2000]}"
        for m in to_compress
    ])
    try:
        resp = get_client().chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是摘要助手，极简输出，不解释。"},
                {"role": "user", "content": f"用3-8句话总结以下对话的关键内容：\n{dialogue}"},
            ],
            stream=False,
        )
        summary_text = resp.choices[0].message.content.strip()
        compressed = {"role": "system", "content": f"[对话历史摘要]\n{summary_text}"}
        console.print(f"[dim]🗜  已压缩 {len(to_compress)} 条旧消息（API摘要）[/]")
        return [system_msg, compressed] + list(recent_msgs)
    except Exception:
        return messages
def list_sessions() -> str:
    """列出所有历史会话文件"""
    if not SESSION_DIR.exists() or not list(SESSION_DIR.glob("*.json")):
        return "（暂无历史会话）"
    sessions = sorted(SESSION_DIR.glob("*.json"), reverse=True)
    lines = [f"共 {len(sessions)} 次会话："]
    for s in sessions[:20]:
        try:
            msgs = json.loads(s.read_text(encoding="utf-8"))
            turns = len([m for m in msgs if m["role"] == "user"])
            first_msg = next((m["content"][:60] for m in msgs if m["role"] == "user"), "")
            lines.append(f"  {s.stem}  ({turns} 轮)  {first_msg}…")
        except Exception:
            lines.append(f"  {s.stem}")
    return "\n".join(lines)

# ===== 系统提示（每轮动态构建）=====

_sp_cache: dict = {"dirty": True, "value": ""}  # 系统提示缓存（仅记忆变化时重建）
_sp_cache_lock = threading.Lock()               # 线程安全锁

def build_system_prompt() -> str:
    """动态构建系统提示，根据任务类型优化token使用"""
    memories = load_memories()
    last_session = load_last_session_context()
    today = date.today().isoformat()
    
    # 基础系统提示（始终包含）
    base_prompt = f"""你是 DS Terminal，运行在用户终端里的 AI 助手，由 DeepSeek 驱动。

今天的日期：{today}

{memories}

{last_session}

---

## 工具能力（主动调用，绝不说"我无法执行"）

### 文件操作
| 工具           | 用途                                                  |
|--------------|-------------------------------------------------------|
| read_file    | 读取文件（支持 offset/limit 按行范围读取）              |
| edit_file    | **精确搜索-替换编辑**（推荐！比 write_file 更安全）    |
| write_file   | 写入/创建文件（全量覆盖，谨慎使用）                    |
| list_dir     | 列出目录内容                                           |
| glob_files   | 按 glob 模式查找文件（支持 ** 递归）                   |
| grep_files   | 在文件/目录中搜索正则，返回匹配行+行号                 |

### 执行能力
| 工具              | 用途                                                  |
|-----------------|-------------------------------------------------------|
| shell            | 执行 Windows PowerShell 命令（短命令）                |
| shell_background | 后台执行耗时命令（下载/安装），立即返回 job_id         |
| shell_status     | 查看后台任务实时进度和输出                             |
| local_model      | 调用本地 Ollama 模型（Gemma 4/Qwen3.5），离线可用     |
| python_exec      | 运行 Python 代码片段                                  |

### 网络与信息
| 工具         | 用途                                                  |
|------------|-------------------------------------------------------|
| web_search | 多引擎搜索：auto/bing/baidu/ddg                        |
| fetch_url  | 抓取任意网页纯文本，直连失败自动代理重试               |
| view_image | 读取本地图片/URL，识别图片内容（视觉）                  |

### Agent 系统（核心能力）
| 工具            | 用途                                                  |
|---------------|-------------------------------------------------------|
| spawn_subagent | **派生专用 Sub-agent**：explore/plan/research/general |
| todo_write     | 写入任务追踪列表，实时显示多步骤任务进度               |
| ask_user       | 主动向用户提问，等待回答后继续（关键决策点使用）       |

### 多实例协作
| 工具           | 用途                                                  |
|--------------|-------------------------------------------------------|
| session_list | 列出所有在线 DS 实例及其收件箱状态                     |
| session_send | 向另一个 DS 实例发送消息/委托任务                      |
| session_recv | 读取本实例的收件箱消息                                 |

上下文：
- 优先中文回答，技术术语保留英文

---

## Agent 思维框架（ReAct + Sub-agent 编排）

**你不是一个简单的问答机器，你是一个自主行动的 Agent。**
面对任务时，遵循以下思维链，直到任务真正完成：

### 标准流程

```
1. Reason（推理）
   - 任务目标是什么？
   - 我现在知道什么？缺少什么信息？
   - 任务复杂度如何？需要 Sub-agent 协助吗？

2. Plan（规划，可选）
   - 超过 3 步的复杂任务：先调用 todo_write 列出所有子任务
   - 不确定方向时：用 spawn_subagent(agent_type="plan") 生成方案

3. Act（行动）
   - 调用工具，一次专注一件事
   - 修改文件时优先用 edit_file（精确），而非 write_file（覆盖）
   - 需要文件探索时：用 spawn_subagent(agent_type="explore") 并行调研
   - 需要网络调研时：用 spawn_subagent(agent_type="research")

4. Observe（观察）
   - 仔细阅读工具返回的结果
   - 结果是否符合预期？需要调整计划吗？
   - 更新 todo_write 状态（pending → in_progress → completed）

5. Repeat（迭代）
   - 根据观察更新理解，继续下一步
   - 直到完整完成任务目标

6. Verify（验证）
   - 最终结果是否真正满足用户需求？
   - 如有必要，补充验证或修正
```

### 工具选用原则

| 场景 | 推荐工具 |
|------|---------|
| 修改已有代码 | `edit_file`（精确替换，不要 write_file） |
| 探索文件/代码库 | `spawn_subagent(explore)` 或 glob/grep |
| 复杂任务规划 | `spawn_subagent(plan)` + `todo_write` |
| 网络信息调研 | `spawn_subagent(research)` |
| 需要用户决策 | `ask_user`（明确提问） |
| 多步骤任务进度 | `todo_write`（每步更新状态） |
| **下载/安装（>5秒）** | **`shell_background` → 立即返回job_id → 继续其他任务** |
| 查看下载进度 | `shell_status(job_id)` 随时查看，不阻塞当前对话 |
| 控制浏览器 | `browser_control(action='snapshot')` 先获取页面结构再操作 |

### 关键原则

- **先探索，再行动**：不确定文件位置时，先用 glob_files 或 list_dir 探索
- **分解复杂任务**：超过 3 步时，先调用 todo_write 规划，再逐步执行
- **错误不是终点**：工具报错时分析原因，尝试替代方案，不要简单重试
- **结果要核实**：写入文件后用 read_file 确认，执行命令后检查输出
- **善用 Sub-agent**：独立子任务可以 spawn_subagent 并行处理，提高效率
- **主动提问**：用户说的模糊时，用 ask_user 精准追问，而非猜测

### 输出格式规范（终端自动美化）

终端使用 `rich` 库渲染 Markdown，以下格式会自动美化为精美样式，**必须主动使用**：

| 场景 | 使用格式 |
|------|---------|
| 对比方案、参数列表、工具说明 | **Markdown 表格** `| 列1 | 列2 |` |
| 代码、命令、脚本 | 代码块 ` ```python ` |
| 步骤、枚举 | 有序列表 `1.` 或无序列表 `-` |
| 强调重点 | 加粗 `**文字**` |

**核心原则：凡是能用表格表达的对比/选项/数据，一律用 Markdown 表格，禁止用文字堆砌。**

---

### 使用 <THINK> 展示推理

遇到复杂问题时，可以用 `<THINK>` 标签展示你的思考过程（不会影响正文显示）：

```
<THINK>
用户想要X，但我不确定Y。我先用 glob_files 找到相关文件，
再用 grep_files 定位具体位置，然后用 read_file 详细阅读后再修改。
</THINK>
```"""
    
        # 使用本地引擎优化提示
    try:
        # 分析任务类型（简单实现）
        task_type = "simple" if len(base_prompt) < 500 else None
        optimized_prompt = _local_engine.optimize_system_prompt_local(base_prompt, task_type)
        
        # 计算节省的token
        savings = _local_engine.estimate_token_savings(len(base_prompt), len(optimized_prompt))
        if savings["savings_percent"] > 10:
            console.print(f"[dim]🔧 系统提示优化: 节省{savings['saved_tokens']} tokens ({savings['savings_percent']:.1f}%)[/]")
            return optimized_prompt
    except Exception as e:
        print(f"[dim]⚠️ 提示优化失败: {e}[/]")
    
    return base_prompt
def _get_sys_prompt() -> str:
    """带脏标志缓存：仅记忆变化时重建，其余轮次直接复用（线程安全）"""
    with _sp_cache_lock:
        if _sp_cache["dirty"]:
            _sp_cache["value"] = build_system_prompt()
            _sp_cache["dirty"] = False
        return _sp_cache["value"]

# ===== 后台退出（保存会话 + 摘要，不阻塞终端）=====
def _do_exit(messages_snap: list, model_name: str):
    """在子线程中保存会话文件并生成摘要，不影响主进程退出速度"""
    save_session(messages_snap)
    generate_and_save_session_summary(messages_snap, model_name)


def _print_token_summary() -> None:
    """退出时打印 token 会话总结（有数据时才显示）。"""
    try:
        if not hasattr(add_simple_token_display, "session_stats"):
            return
        stats = add_simple_token_display.session_stats
        if stats["total_calls"] == 0:
            return
        total  = stats["total_tokens"]
        prompt = stats["total_prompt"]
        compl  = stats["total_completion"]
        calls  = stats["total_calls"]
        pct    = prompt / total * 100 if total else 0
        cost   = total / 1_000_000 * 0.14
        console.print("\n[dim]" + "─" * 52 + "[/]")
        console.print("[bold cyan]📊 Token 会话总结[/]")
        console.print(
            f"[dim]调用 {calls} 次 | 总计 {total:,} tokens "
            f"({prompt:,}↑ {compl:,}↓)[/]"
        )
        console.print(
            f"[dim]均值 {total//calls:,}/次 | 输入占比 {pct:.1f}% | "
            f"💰 ${cost:.4f}[/]"
        )
        if pct > 80:
            console.print("[dim]💡 输入占比偏高，可 /clear 或压缩记忆[/]")
        console.print("[dim]" + "─" * 52 + "[/]\n")
    except Exception:
        pass


# =============================================================================
# ===== 固定底部输入框（Claude Code 风格）=====
# 使用 ANSI 滚动区域将终端底部 3 行永久保留给输入框。
# 上方所有 console.print() 输出在滚动区域内自然滚动，互不干扰。
#
# 终端布局（高度 H）：
#   行 1   …  H-3 : 滚动区域 — 所有 DS 输出在此向上滚
#   行 H-2        : ─────────────────────  上边框（固定）
#   行 H-1        : > █                    输入行（固定）
#   行 H          : ─────────────────────  下边框（固定）
# =============================================================================

class _SimpleInputBox:
    """简单输入框控制器 - 没有固定边框，兼容模式。"""

    def __init__(self):
        pass

    def setup(self):
        """启动时调用，什么都不做。"""
        pass

    def before_read(self):
        """读取输入前调用，什么都不做。"""
        pass

    def ensure_scroll_position(self):
        """确保滚动位置，什么都不做。"""
        pass

    def after_read(self):
        """读取输入后调用，什么都不做。"""
        pass

    def teardown(self):
        """退出时调用，什么都不做。"""
        pass

# 全局单例 - 使用简单输入框（无固定边框）
_ibox = _SimpleInputBox()


def graceful_exit(messages: list, model_key: str):
    _ibox.teardown()                     # 先恢复终端
    _print_token_summary()
    snap = list(messages)
    t = threading.Thread(target=_do_exit, args=(snap, MODELS[model_key]), daemon=True)
    t.start()
    console.print("[dim]Bye.[/]")
    t.join(timeout=10)                   # 最多等 10s，超时自动放弃

# ===== 工具定义（传给 API）=====
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "执行 Windows PowerShell 命令，返回 stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell 命令"},
                    "timeout": {"type": "integer", "default": 300, "description": "超时秒数"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容。超 80000 字符时可用 offset/limit 按行范围读取",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "encoding": {"type": "string", "default": "utf-8"},
                    "offset": {"type": "integer", "default": 0, "description": "起始行号（0-indexed）"},
                    "limit":  {"type": "integer", "default": 0, "description": "读取行数，0=全部"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件（自动创建父目录），返回写入字节数",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "encoding": {"type": "string", "default": "utf-8"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录下的文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": ".", "description": "目录路径"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": "在当前进程内执行 Python 代码，捕获 stdout/stderr 返回",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python 代码（可多行）"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "多引擎网络搜索，支持国内外网站。engine 选项：auto（默认：必应→DDG）/ bing（必应，国内直连）/ baidu（百度，纯中文）/ ddg（DuckDuckGo，走本地代理）",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":       {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "default": 10, "description": "返回结果数量"},
                    "engine":      {"type": "string",  "default": "auto",
                                   "description": "搜索引擎：auto / bing / baidu / ddg"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "抓取任意网页纯文本，自动检测编码（GBK/UTF-8）。直连失败时自动走本地代理重试。use_proxy=true 可强制走代理（访问 Twitter/Reddit 等被封网站）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url":       {"type": "string",  "description": "网页 URL（http 或 https）"},
                    "max_chars": {"type": "integer", "default": 8000,  "description": "返回最大字符数"},
                    "use_proxy": {"type": "boolean", "default": False, "description": "强制走本地代理"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "按 glob 模式查找文件，支持 ** 递归。例：'**/*.py' 找所有Python文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern":  {"type": "string", "description": "glob 模式，如 '**/*.py'"},
                    "base_dir": {"type": "string", "default": ".", "description": "搜索起始目录"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": "在文件中搜索正则表达式，返回匹配行和行号。用于快速定位代码/内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern":      {"type": "string", "description": "正则表达式"},
                    "path":         {"type": "string", "description": "搜索路径（文件或目录）"},
                    "file_pattern": {"type": "string", "default": "*", "description": "文件名过滤，如 '*.py'"},
                    "max_results":  {"type": "integer", "default": 500}
                },
                "required": ["pattern", "path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "读取本地图片文件（或图片URL），识别并描述图片内容。当用户让你查看、分析、识别图片时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "图片路径（本地绝对/相对路径）或图片URL（http/https）"},
                    "question": {"type": "string", "default": "请详细描述这张图片的内容", "description": "关于图片的具体问题"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "session_list",
            "description": "列出所有在线的 DS 实例，查看谁在线、各自的收件箱消息数",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "session_send",
            "description": "向另一个 DS 实例的收件箱发送消息（文本或任务委托）",
            "parameters": {
                "type": "object",
                "properties": {
                    "target":  {"type": "string", "description": "目标实例名（如 'ds-worker'）"},
                    "message": {"type": "string", "description": "消息内容"}
                },
                "required": ["target", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "session_recv",
            "description": "读取当前实例的收件箱消息",
            "parameters": {
                "type": "object",
                "properties": {
                    "clear": {"type": "boolean", "default": False, "description": "读取后是否清空收件箱"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "在 DS 的长期记忆（~/.ds_memory/）中用 BM25 快速检索相关信息。当用户问'你还记得...'、'之前我说过...'、或需要回忆历史对话/项目/偏好时，必须优先调用此工具。比 grep_files 更智能，自动按相关度排序。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":      {"type": "string", "description": "搜索关键词或问题描述（支持中英文混合）"},
                    "top_k":      {"type": "integer", "default": 5, "description": "返回最相关的前 N 个文件"},
                    "memory_dir": {"type": "string", "default": "", "description": "记忆目录路径，留空则用 ~/.ds_memory/"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_control",
            "description": "控制本地 Chrome 浏览器（BrowserWing，自动启动/重连）。标准工作流：1.navigate(url) → 2.snapshot()获取@e1/@e2元素ID → 3.click(identifier='@e1') → 4.type(identifier='@e3',text='内容') → 5.press_key(key='Enter')。连接中断会自动重启。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["navigate","snapshot","click","type","press_key","select","fill_form",
                                 "extract","page_text","page_info","screenshot","exec_js","scroll",
                                 "wait","hover","go_back","go_forward","reload","tabs",
                                 "file_upload","drag","handle_dialog","console_messages",
                                 "network_requests","resize","ai_explore","status","help"],
                        "description": "操作类型。先调 snapshot 获取元素ID(@e1/@e2)，再用 click/type 操作"
                    },
                    "url":        {"type": "string", "description": "目标URL（navigate时必填）"},
                    "identifier": {"type": "string", "description": "元素标识（@e1/@e2 最准确，也可用CSS选择器或文字内容）"},
                    "text":       {"type": "string", "description": "输入文字（type时使用）/ 键名（press_key）/ 选项（select）"},
                    "script":     {"type": "string", "description": "JS代码（exec_js），如 '() => document.title'"},
                    "task":       {"type": "string", "description": "任务描述（ai_explore时使用）"},
                    "selector":   {"type": "string", "description": "CSS选择器（extract/drag目标时使用）"},
                    "key":        {"type": "string", "description": "按键名（press_key）：Enter/Tab/Escape/ArrowDown/ArrowUp"},
                    "fields":     {"type": "array",  "description": "批量表单字段 [{\"name\":\"email\",\"value\":\"...\"}]（fill_form时使用）"},
                    "multiple":   {"type": "boolean", "default": False, "description": "extract时是否提取多个元素"},
                    "wait_until": {"type": "string", "default": "domcontentloaded", "description": "navigate等待条件：load/domcontentloaded/networkidle"},
                    "timeout":    {"type": "integer", "default": 30, "description": "超时秒数"},
                    "save_screenshot": {"type": "string", "description": "截图保存路径，默认桌面 screenshot.png"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "local_model",
            "description": "调用本地 Ollama 模型（Gemma 4 E4B / Qwen3.5 等）。离线可用，支持多模态。action=list查模型，action=ask提问，action=status检查状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "list（列出模型）/ ask（提问）/ status（检查Ollama）"},
                    "prompt": {"type": "string", "description": "问题内容（action=ask时必填）"},
                    "model":  {"type": "string", "default": "gemma4:e4b", "description": "模型名，如 gemma4:e4b / qwen3.5:9b"},
                    "system": {"type": "string", "default": "", "description": "系统提示词"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shell_background",
            "description": "后台执行耗时的shell命令（下载/安装/编译等），立即返回job_id，不会超时。适合所有需要等待的长时间任务（pip install、ollama pull、wget下载等）。启动后用 shell_status 查看实时进度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell 命令"},
                    "timeout": {"type": "integer", "default": 3600, "description": "最长等待秒数，默认1小时"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shell_status",
            "description": "查看后台任务(shell_background)的实时进度和输出。可随时调用，任务运行中也能看到最新输出。状态显示：运行中/已完成/已失败。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "shell_background 返回的任务ID"},
                    "tail_lines": {"type": "integer", "default": 60, "description": "显示最后N行输出"}
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "任务100%完成且已验证成功后，调用此函数终止循环。这是结束任务的唯一合法方式——不调用此函数则任务永远不会停止。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "完成报告：做了什么、产出是什么、如何确认成功"}
                },
                "required": ["summary"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "精确搜索-替换编辑文件。old_string 必须在文件中唯一（提供足够上下文），不会覆盖整个文件，比 write_file 更安全。默认只替换一次；replace_all=true 替换所有匹配。修改代码时优先用此工具而非 write_file。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_string": {"type": "string", "description": "要被替换的精确字符串（必须在文件中唯一，提供足够行上下文）"},
                    "new_string": {"type": "string", "description": "替换后的新字符串"},
                    "replace_all": {"type": "boolean", "default": False, "description": "是否替换所有匹配，默认 false（只替换唯一匹配）"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "派生专用 Sub-agent 处理特定子任务，拥有独立的对话上下文。适合需要专注完成单一子任务的场景。agent_type：explore（只读探索文件/代码）、plan（架构规划，输出详细方案）、research（网络搜索调研）、general（通用，可用全部工具）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "3-5字的任务描述（如：探索项目结构、调研最佳实践）"},
                    "prompt": {"type": "string", "description": "给 Sub-agent 的详细任务指令，说清背景、目标、输出格式"},
                    "agent_type": {"type": "string", "enum": ["explore", "plan", "research", "general"], "default": "general", "description": "agent 类型，决定可用工具集和系统提示"},
                    "model": {"type": "string", "enum": ["chat", "r1"], "description": "使用的模型（可选，默认按 agent_type 选择）"}
                },
                "required": ["description", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "写入/更新任务追踪列表。在多步骤复杂任务开始时调用，列出所有子任务；每完成一步更新状态。帮助用户实时追踪进度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "完整的任务列表（每次传入全量数组）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "任务 ID（如 '1', '2a'）"},
                                "content": {"type": "string", "description": "任务内容描述"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "状态"},
                                "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级"}
                            },
                            "required": ["id", "content", "status"]
                        }
                    }
                },
                "required": ["todos"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "主动向用户提问，暂停执行等待用户回答后继续。用于需要用户决策的关键节点（选择方案、确认危险操作、补充信息）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要问用户的问题"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "可选选项列表（不提供则为开放性回答）"}
                },
                "required": ["question"]
            }
        }
    },
]

# ===== 工具实现 =====

# ===== 增强版Shell工具实现 =====
# 在tool_shell函数之前添加以下代码

# 预编译正则表达式（性能优化）
_SHELL_RISKY_PATTERNS = [
    (re.compile(r"Read-Host", re.IGNORECASE), "交互式命令，需要用户输入", 30),
    (re.compile(r"Start-Sleep.*?([5-9][0-9]|[0-9]{3,})", re.IGNORECASE), "长时间睡眠命令", 600),
    (re.compile(r"-Recurse.*[cC]:[\/]", re.IGNORECASE), "全盘递归搜索可能很慢", 180),
    (re.compile(r"Invoke-WebRequest|Test-NetConnection|ping.*-t", re.IGNORECASE), "网络命令可能被阻塞", 120),
    (re.compile(r"Get-ChildItem.*-Recurse.*-ErrorAction", re.IGNORECASE), "递归搜索带错误处理", 150),
]

_SHELL_DANGEROUS_PATTERNS = [
    (re.compile(r"Remove-Item.*-Recurse.*-Force", re.IGNORECASE), "强制递归删除"),
    (re.compile(r"Format-Volume", re.IGNORECASE), "格式化磁盘"),
    (re.compile(r"Stop-Computer|Restart-Computer", re.IGNORECASE), "关机/重启"),
    (re.compile(r"Set-ExecutionPolicy.*Unrestricted", re.IGNORECASE), "修改执行策略"),
]

_SHELL_ERROR_EXPLANATIONS = {
    1: "一般错误",
    2: "命令语法错误",
    5: "访问被拒绝（权限不足）",
    9009: "命令不存在或路径错误",
    3221225786: "内存访问冲突（通常为C++程序崩溃）",
}

# 增强版Shell执行器（线程安全）
class _EnhancedShellExecutor:
    """增强版Shell执行器（内部类）"""
    
    def __init__(self):
        self.command_history = []
        self.history_lock = threading.Lock()
    
    def _validate_command(self, command: str) -> tuple:
        """验证命令安全性"""
        # 检查命令长度
        if len(command) > 10000:
            return False, f"命令过长（{len(command)} > 10000）"
        
        # 检查危险操作
        for pattern, description in _SHELL_DANGEROUS_PATTERNS:
            if pattern.search(command):
                return False, f"危险操作: {description}"
        
        # 基本语法检查
        if command.strip().startswith("&") or command.strip().startswith(";"):
            return False, "命令以危险字符开头"
        
        return True, ""
    
    def _analyze_command(self, command: str) -> dict:
        """分析命令风险"""
        warnings = []
        suggested_timeout = 120  # 默认超时
        
        # 检查风险模式
        for pattern, description, cmd_timeout in _SHELL_RISKY_PATTERNS:
            if pattern.search(command):
                warnings.append(f"⚠️ {description}")
                suggested_timeout = max(suggested_timeout, cmd_timeout)
        
        # 检查命令长度
        if len(command) > 1000:
            warnings.append("⚠️ 命令过长，可能包含复杂逻辑")
            suggested_timeout = max(suggested_timeout, 180)
        
        return {
            "warnings": warnings,
            "suggested_timeout": suggested_timeout,
            "is_risky": len(warnings) > 0
        }
    
    def _calculate_timeout(self, command: str, user_timeout: int) -> int:
        """计算实际超时时间"""
        if user_timeout != 300:  # 用户指定了超时
            return max(user_timeout, 10)  # 最少10秒
        
        # 用户未指定，使用分析建议
        analysis = self._analyze_command(command)
        return analysis["suggested_timeout"]
    
    def execute(self, command: str, timeout: int = 300) -> str:
        """
        执行命令（增强版）
        
        Args:
            command: PowerShell命令
            timeout: 超时时间（秒），默认300
            
        Returns:
            命令执行结果
        """
        # 1. 验证命令
        is_valid, error_msg = self._validate_command(command)
        if not is_valid:
            return f"[validation error] {error_msg}"
        
        # 2. 分析命令风险
        analysis = self._analyze_command(command)
        
        # 3. 计算实际超时
        actual_timeout = self._calculate_timeout(command, timeout)
        
        # 4. 构建输出（可选显示警告）
        output_parts = []
        if analysis["warnings"]:
            warning_header = '命令分析'

            warning_list = "".join(f"  • {w}" for w in analysis["warnings"])
            output_parts.append(warning_header + warning_list )
        
        try:
            # 5. 执行命令
            start_time = time.time()
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                timeout=actual_timeout,
                encoding="utf-8",
                errors="replace"
            )
            elapsed = time.time() - start_time
            
            # 6. 处理输出
            output_parts.append(f"[执行时间: {elapsed:.2f}秒]")
            
            # 处理标准输出
            if result.stdout and result.stdout.strip():
                stdout = result.stdout.strip()
                # 限制输出大小，防止内存问题
                if len(stdout) > 50000:
                    stdout = stdout[:50000] + \
                            f"[... 输出被截断，总长度 {len(result.stdout):,} 字符]"
                output_parts.append(stdout)
            
            # 处理标准错误
            if result.stderr and result.stderr.strip():
                stderr = result.stderr.strip()
                if len(stderr) > 25000:
                    stderr = stderr[:25000] + "[... 错误输出被截断]"
                output_parts.append(f"[stderr]{stderr}")
            
            # 处理返回码
            if result.returncode != 0:
                exit_info = f"[exit {result.returncode}]"
                if result.returncode in _SHELL_ERROR_EXPLANATIONS:
                    exit_info += f" - {_SHELL_ERROR_EXPLANATIONS[result.returncode]}"
                output_parts.append(exit_info)
            
            # 7. 合并输出
            final_output = "".join(output_parts)
            
            # 8. 记录历史（线程安全）
            with self.history_lock:
                # 限制历史记录大小
                if len(self.command_history) >= 1000:
                    self.command_history.pop(0)
                
                self.command_history.append({
                    "command": command[:200],  # 只保存前200字符
                    "timeout": actual_timeout,
                    "elapsed": elapsed,
                    "success": result.returncode == 0,
                    "timestamp": time.time()
                })
            
            return final_output if final_output.strip() else "(命令执行成功，无输出)"
            
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            
            # 详细的超时信息
            timeout_info = [
                f"[timeout] 命令执行超时（{actual_timeout}秒）",
                f"[info] 实际执行: {elapsed:.2f}秒",
                "",
                "可能原因:",
                "  1. 命令需要更长时间执行",
                "  2. 命令在等待用户输入",
                "  3. 网络/资源问题",
                "",
                "建议:",
                f"  • 增加超时: timeout={actual_timeout*2}",
                "  • 分解复杂命令",
                "  • 检查命令是否等待输入",
            ]
            
            base_output = "".join(output_parts) if output_parts else ""
            return f"{base_output}" + "".join(timeout_info) if base_output else "".join(timeout_info)
            
        except Exception as e:
            # 不再完全忽略异常
            error_info = [
                "[error] 命令执行失败",
                f"错误类型: {type(e).__name__}",
                f"错误信息: {str(e)}",
                "",
                "建议:",
                "  1. 检查命令语法",
                "  2. 确保PowerShell可用",
                "  3. 检查权限和路径",
            ]
            
            base_output = "".join(output_parts) if output_parts else ""
            return f"{base_output}" + "".join(error_info) if base_output else "".join(error_info)

# 单例实例
_SHELL_EXECUTOR_INSTANCE = None
_SHELL_EXECUTOR_LOCK = threading.Lock()

def _get_shell_executor():
    """获取Shell执行器单例（线程安全）"""
    global _SHELL_EXECUTOR_INSTANCE
    if _SHELL_EXECUTOR_INSTANCE is None:
        with _SHELL_EXECUTOR_LOCK:
            if _SHELL_EXECUTOR_INSTANCE is None:
                _SHELL_EXECUTOR_INSTANCE = _EnhancedShellExecutor()
    return _SHELL_EXECUTOR_INSTANCE

# ===== 工具实现 =====

def tool_shell(command: str, timeout: int = 300) -> str:
    """增强版shell工具 - 完全兼容原版API"""
    executor = _get_shell_executor()
    return executor.execute(command, timeout)


# ===== 后台Shell工具（解决下载/长时间任务进度可见性问题）=====

import tempfile
import uuid as _uuid_mod

_BACKGROUND_JOBS: dict = {}
_BACKGROUND_JOBS_LOCK = threading.Lock()


def tool_shell_background(command: str, timeout: int = 3600) -> str:
    """后台执行耗时命令，立即返回 job_id，不会超时。
    适合：pip install、ollama pull、wget、npm install 等长时间任务。
    用 tool_shell_status(job_id) 随时查看实时进度。
    """
    log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="ds_job_")
    os.close(log_fd)
    job_id = _uuid_mod.uuid4().hex[:8]
    try:
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        with _BACKGROUND_JOBS_LOCK:
            _BACKGROUND_JOBS[job_id] = {
                "proc": proc,
                "log_path": log_path,
                "log_file": log_file,
                "start_time": time.time(),
                "command": command[:300],
                "timeout": timeout,
            }
        return (
            f"[后台任务已启动]\n"
            f"job_id : {job_id}\n"
            f"PID    : {proc.pid}\n"
            f"命令   : {command[:120]}\n\n"
            f"→ 调用 shell_status(\"{job_id}\") 查看实时进度\n"
            f"→ 每隔 30-60 秒检查一次即可，无需频繁轮询"
        )
    except Exception as e:
        try:
            os.unlink(log_path)
        except Exception:
            pass
        return f"[error] 启动后台任务失败: {e}"


def tool_shell_status(job_id: str, tail_lines: int = 60) -> str:
    """查看后台任务的实时进度和输出。
    任务运行中也可调用，每次返回最新的 tail_lines 行输出。
    """
    with _BACKGROUND_JOBS_LOCK:
        job = _BACKGROUND_JOBS.get(job_id)

    if not job:
        # 模糊匹配前缀
        with _BACKGROUND_JOBS_LOCK:
            matches = [k for k in _BACKGROUND_JOBS if k.startswith(job_id)]
        if matches:
            job_id = matches[0]
            with _BACKGROUND_JOBS_LOCK:
                job = _BACKGROUND_JOBS[job_id]
        else:
            with _BACKGROUND_JOBS_LOCK:
                all_jobs = list(_BACKGROUND_JOBS.keys())
            if not all_jobs:
                return f"[error] 找不到任务 {job_id!r}，当前无后台任务"
            listing = "\n".join(
                f"  {k}: {_BACKGROUND_JOBS[k]['command'][:80]}"
                for k in all_jobs
            )
            return f"[error] 找不到任务 {job_id!r}\n\n当前后台任务:\n{listing}"

    proc = job["proc"]
    elapsed = int(time.time() - job["start_time"])
    return_code = proc.poll()

    if return_code is None:
        status = f"运行中 ⏳ (已用时 {elapsed}s)"
        is_done = False
    elif return_code == 0:
        status = f"已完成 ✓ (耗时 {elapsed}s)"
        is_done = True
    else:
        status = f"已退出 ✗ (退出码:{return_code}, 耗时:{elapsed}s)"
        is_done = True

    # 读取日志
    try:
        with open(job["log_path"], "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        shown = lines[-tail_lines:] if total > tail_lines else lines
        output = "".join(shown).strip()
        trunc_note = f"(共 {total} 行，显示最后 {len(shown)} 行)\n" if total > tail_lines else f"(共 {total} 行)\n"
    except Exception as e:
        output = f"[读取日志失败: {e}]"
        trunc_note = ""

    result = (
        f"[任务 {job_id}]\n"
        f"状态  : {status}\n"
        f"命令  : {job['command'][:120]}\n"
        f"\n--- 最新输出 ---\n"
        f"{trunc_note}"
        f"{output if output else '(暂无输出)'}"
    )

    # 超时强制终止
    if not is_done and elapsed > job["timeout"]:
        try:
            proc.terminate()
        except Exception:
            pass
        result += f"\n\n[⚠️ 任务已超时 ({job['timeout']}s)，进程已终止]"

    return result


def tool_local_model(action: str, prompt: str = "",
                     model: str = "gemma4:e4b", system: str = "") -> str:
    """调用本地 Ollama 模型（Gemma 4 / Qwen3.5 等）。
    action: list（列出已安装模型）| ask（单轮问答）| status（检查Ollama是否运行）
    """
    import urllib.request, urllib.error, json as _json

    OLLAMA_BASE = "http://localhost:11434"

    if action == "status":
        try:
            urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3)
            if _OLLAMA_AVAILABLE:
                return _list_local_models()
            return "Ollama 运行中 ✓"
        except Exception:
            return "Ollama 未启动，请确认 Ollama 服务已运行"

    if action == "list":
        if _OLLAMA_AVAILABLE:
            return _list_local_models()
        return "[error] 本地模型库未加载"

    if action == "ask":
        if not prompt:
            return "[error] 缺少 prompt 参数"
        if _OLLAMA_AVAILABLE:
            return _chat_local(
                messages=[{"role": "user", "content": prompt}],
                model=model
            )
        # fallback: 直接调用
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        try:
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/chat", data=data,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = _json.loads(resp.read())
            return result["message"]["content"]
        except urllib.error.URLError:
            return "[error] Ollama 未启动，请确认 Ollama 服务已运行"
        except Exception as e:
            return f"[error] {e}"

    return f"[error] 未知 action: {action!r}，可选: list / ask / status"


def tool_read_file(path: str, encoding: str = "utf-8",
                   offset: int = 0, limit: int = 0) -> str:
    try:
        p = Path(path).expanduser()
        content = p.read_text(encoding=encoding, errors="replace")
        if offset or limit:
            lines = content.split("\n")
            total = len(lines)
            start = max(0, offset)
            end = (start + limit) if limit else total
            content = "\n".join(lines[start:end])
            if end < total:
                content += f"\n[... 显示第 {start+1}-{end} 行，共 {total} 行]"
        elif len(content) > 80000:
            content = content[:80000] + f"\n[... truncated — total {len(content):,} chars]"
        return content
    except Exception as e:
        return f"[error] {e}"

def tool_write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """增强版write_file工具（提供更详细的错误信息）"""
    try:
        # 智能路径修复
        import re
        if path:
            # 修复常见路径问题
            fixed_path = path.replace('\\', '/').replace('\\', '/')
            # 修复转义字符
            escape_fixes = [
                (r'\\t', '/t'),  # 制表符
                (r'\\n', '/n'),  # 换行符
                (r'\\r', '/r'),  # 回车符
            ]
            for pattern, replacement in escape_fixes:
                fixed_path = re.sub(pattern, replacement, fixed_path)
            # 相对路径修复
            if not ('/' in fixed_path or '\\' in fixed_path or ':' in fixed_path):
                fixed_path = './' + fixed_path
            path = fixed_path
        
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        size = p.stat().st_size
        
        # 成功信息（保持与原格式兼容）
        success_msg = f"OK — {size:,} bytes → {p.resolve()}"
        
        # 额外信息
        if size == 0:
            success_msg += " [⚠️ 文件大小为0字节]"
        if len(content) > 10000:
            success_msg += f" [📊 内容长度: {len(content):,} 字符]"
        
        return success_msg
        
    except FileNotFoundError as e:
        return f"[error] 路径错误: {e} (提示: 检查路径格式)"
    
    except PermissionError as e:
        return f"[error] 权限错误: {e} (提示: 文件被占用或无写入权限)"
    
    except UnicodeEncodeError as e:
        return f"[error] 编码错误: {e} (提示: 尝试 encoding='utf-8' 或 encoding='gbk')"
    
    except OSError as e:
        if "Invalid argument" in str(e):
            return f"[error] 无效路径: {e} (提示: 路径包含无效字符)"
        return f"[error] 系统错误: {e}"
    
    except Exception as e:
        # 简化错误信息，保持与原格式兼容
        error_msg = str(e)
        if len(error_msg) > 100:
            error_msg = error_msg[:100] + "..."
        return f"[error] {error_msg}"

def tool_list_dir(path: str = ".") -> str:
    try:
        p = Path(path).expanduser()
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [str(p.resolve())]
        for item in items:
            if item.is_dir():
                lines.append(f"  DIR   {item.name}/")
            else:
                sz = item.stat().st_size
                if sz < 1024:       sz_str = f"{sz}B"
                elif sz < 1024**2:  sz_str = f"{sz//1024}KB"
                else:               sz_str = f"{sz//1024//1024}MB"
                lines.append(f"  FILE  {item.name:<42} {sz_str:>6}")
        return "\n".join(lines)
    except Exception as e:
        return f"[error] {e}"

def tool_python_exec(code: str) -> str:
    """
    执行 Python 代码，实时流式显示 print() 输出（进度可见）。
    exec 环境自动注入 progress(msg) 辅助函数，便于代码主动上报进度节点。
    返回值包含全部 stdout/stderr + 执行耗时，DeepSeek 可据此判断执行情况。
    """
    collected_out: list = []
    collected_err: list = []

    class _Tee:
        """同时写入收集缓冲区 + 实时打印到终端（dim 样式区分工具输出）"""
        def __init__(self, storage: list, is_err: bool = False):
            self._storage = storage
            self._is_err  = is_err

        def write(self, s: str) -> int:
            self._storage.append(s)
            if s.strip():
                color = "\033[31m" if self._is_err else "\033[2m"
                console.file.write(f"{color}  {s}\033[0m")
                console.file.flush()
            return len(s)

        def flush(self):
            console.file.flush()

        # io 接口兼容
        def isatty(self): return False
        def readable(self): return False
        def writable(self): return True
        def seekable(self): return False

    def _progress(msg: str):
        """
        在 exec 代码中调用 progress('消息') 向 DeepSeek 上报进度节点。
        示例：progress('第1步完成，已处理100行')
        """
        line = f"[progress] {msg}\n"
        collected_out.append(line)
        console.file.write(f"\033[36m  ◦ {msg}\033[0m\n")
        console.file.flush()

    exec_globals = {
        "__name__": "__main__",
        "progress": _progress,  # 注入进度上报函数
    }

    tee_out = _Tee(collected_out, is_err=False)
    tee_err = _Tee(collected_err, is_err=True)

    start_time = time.time()
    try:
        with redirect_stdout(tee_out), redirect_stderr(tee_err):  # type: ignore[arg-type]
            exec(compile(code, "<ds_python_exec>", "exec"), exec_globals)
    except Exception:
        collected_err.append(traceback.format_exc())
    elapsed = time.time() - start_time

    out = "".join(collected_out)
    err = "".join(collected_err)
    result = out + ("\n[stderr]\n" + err if err else "")

    # 执行耗时注入（DeepSeek 可见）
    time_info = f"[耗时: {elapsed:.2f}s]"
    if result.strip():
        return f"{time_info}\n{result.strip()}"
    return f"{time_info}\n(no output)"

def tool_glob_files(pattern: str, base_dir: str = ".") -> str:
    try:
        base = Path(base_dir).expanduser()
        matches = sorted(base.glob(pattern))
        if not matches:
            return f"(无匹配文件: {pattern} in {base.resolve()})"
        lines = [f"找到 {len(matches)} 个文件，模式 '{pattern}':"]
        for m in matches[:1000]:
            try:
                rel = m.relative_to(base)
            except ValueError:
                rel = m
            if m.is_dir():
                lines.append(f"  DIR   {rel}/")
            else:
                sz = m.stat().st_size
                sz_str = f"{sz//1024//1024}MB" if sz >= 1024**2 else (f"{sz//1024}KB" if sz >= 1024 else f"{sz}B")
                lines.append(f"  {rel}  ({sz_str})")
        if len(matches) > 1000:
            lines.append(f"  ... 还有 {len(matches)-1000} 个")
        return "\n".join(lines)
    except Exception as e:
        return f"[error] {e}"

def tool_grep_files(pattern: str, path: str,
                    file_pattern: str = "*", max_results: int = 500) -> str:
    """搜索文件内容。优先用 rg（ripgrep）加速，不可用时降级为纯 Python。"""
    try:
        p = Path(path).expanduser()

        # ── 优先路径 1：ds_tools（Rust 并行 grep，最快）──────────────────
        import shutil
        _ds_tools_bin = shutil.which("ds_tools") or str(Path.home() / "bin" / "ds_tools.exe")
        if Path(_ds_tools_bin).exists():
            try:
                proc = subprocess.run(
                    [_ds_tools_bin, "grep", pattern, str(p),
                     "--glob", file_pattern, "--max", str(max_results)],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=20,
                )
                if proc.returncode == 0:
                    return proc.stdout.rstrip()
            except subprocess.TimeoutExpired:
                pass

        # ── 优先路径 2：ripgrep（若已安装）──────────────────────────────
        try:
            rg_cmd = [
                "rg",
                "--color=never", "--no-heading", "--line-number",
                "--ignore-case", "--max-count", str(max_results),
                "--glob", file_pattern, pattern, str(p),
            ]
            proc = subprocess.run(
                rg_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            if proc.returncode in (0, 1):
                if not lines:
                    return f"(无匹配: '{pattern}' in {path})"
                header = f"[rg] 找到 {len(lines)} 处匹配:"
                if len(lines) >= max_results:
                    header += f" (已截断至 {max_results} 条)"
                return header + "\n" + "\n".join(lines)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # ── 降级路径：纯 Python ──────────────────────────────────────────
        import re as re_module
        regex = re_module.compile(pattern, re_module.IGNORECASE)
        results = []
        files = [p] if p.is_file() else list(p.rglob(file_pattern))
        for f in sorted(files):
            if not f.is_file():
                continue
            try:
                file_lines = f.read_text(encoding="utf-8", errors="replace").split("\n")
                for i, line in enumerate(file_lines, 1):
                    if regex.search(line):
                        try:
                            rel = f.relative_to(p) if p.is_dir() else f.relative_to(p.parent)
                        except ValueError:
                            rel = f
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= max_results:
                            break
            except Exception:
                pass
            if len(results) >= max_results:
                break
        if not results:
            return f"(无匹配: '{pattern}' in {path})"
        header = f"找到 {len(results)} 处匹配:"
        if len(results) >= max_results:
            header += f" (已截断至 {max_results} 条)"
        return header + "\n" + "\n".join(results)
    except Exception as e:
        return f"[error] {e}"

# ===== 代理自动检测 =====

_proxy_cache: dict = {"value": None, "detected": False}  # 进程内单次检测缓存

def _detect_local_proxy() -> str:
    """自动检测本地 HTTP 代理端口（Clash/v2rayN/Shadowsocks 等），结果缓存进程内复用"""
    if _proxy_cache["detected"]:
        return _proxy_cache["value"] or ""
    import socket
    result = ""
    # 1. 优先读环境变量
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        v = os.environ.get(var, "")
        if v and "://" in v:
            result = v
            break
    # 2. 探测常见本地端口（0.3s 超时快速扫描）
    if not result:
        for port in (7889, 7890, 10809, 7891, 1080, 8080, 8118, 1087):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.3)
                err = s.connect_ex(("127.0.0.1", port))
                s.close()
                if err == 0:
                    result = f"http://127.0.0.1:{port}"
                    break
            except OSError:
                pass
    _proxy_cache["value"] = result
    _proxy_cache["detected"] = True
    return result


def _http_get(url: str, headers: dict = None, timeout: int = 15,
              use_proxy: bool = False) -> bytes:
    """统一 HTTP GET，返回原始字节。
    use_proxy=True  → 使用本地代理（Clash/v2ray），用于国际网站
    use_proxy=False → 直连（默认），用于国内网站
    """
    import urllib.request
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    if headers:
        base_headers.update(headers)
    req = urllib.request.Request(url, headers=base_headers)
    if use_proxy:
        proxy = _detect_local_proxy()
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
        else:
            opener = urllib.request.build_opener()   # 系统代理兜底
    else:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})          # 直连，禁用代理
        )
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def _decode_html(raw: bytes) -> str:
    """自动检测编码（Content-Type meta → UTF-8 兜底），解码为字符串"""
    charset = None
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096], re.I)
    if m:
        charset = m.group(1).decode("ascii", errors="replace")
    charset = charset or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _strip_html(html_text: str, max_lines: int = 500) -> str:
    """提取 HTML 纯文本，跳过 script/style/svg 等不可见标签"""
    from html.parser import HTMLParser
    import html as _hl

    class _Extractor(HTMLParser):
        SKIP  = {"script", "style", "head", "meta", "link", "noscript", "svg", "iframe"}
        BLOCK = {"p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                 "li", "tr", "td", "th", "article", "section", "header", "footer", "nav"}
        def __init__(self):
            super().__init__()
            self.parts = []
            self._skip = 0
        def handle_starttag(self, tag, attrs):
            if tag in self.SKIP:   self._skip += 1
            if tag in self.BLOCK:  self.parts.append("\n")
        def handle_endtag(self, tag):
            if tag in self.SKIP:   self._skip = max(0, self._skip - 1)
        def handle_data(self, data):
            if self._skip == 0:    self.parts.append(data)

    p = _Extractor()
    p.feed(html_text)
    raw = _hl.unescape("".join(p.parts))
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    return "\n".join(lines[:max_lines])


def _fmt_results(query: str, items: list, engine: str) -> str:
    """格式化搜索结果列表"""
    import html as _hl
    parts = [f"**[{engine}] 搜索：{query}**（{len(items)} 条结果）\n"]
    for i, r in enumerate(items, 1):
        title   = _hl.unescape(r.get("title", "")).strip()
        url     = r.get("url", "").strip()
        snippet = _hl.unescape(r.get("snippet", "")).strip()
        parts.append(f"{i}. **{title}**\n   {url}\n   {snippet}\n")
    return "\n".join(parts)


# ===== 各搜索引擎实现 =====

def _search_bing(query: str, max_results: int) -> list:
    """Bing 搜索（国内直连，无需代理）"""
    import urllib.parse
    from html.parser import HTMLParser
    import html as _hl

    class _BingParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.results = []
            self._in_algo = False
            self._state   = None
            self._cur     = {}
            self._buf     = []

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            cls = d.get("class", "")
            if tag == "li" and "b_algo" in cls:
                self._in_algo = True
                self._cur = {}
            elif self._in_algo and tag == "h2":
                self._state = "h2"
            elif self._state == "h2" and tag == "a":
                self._state = "title"
                self._cur["url"] = d.get("href", "")
                self._buf = []
            elif self._in_algo and self._state is None and tag == "p":
                if not self._cur.get("snippet"):
                    self._state = "snippet"
                    self._buf = []

        def handle_endtag(self, tag):
            if tag == "li" and self._in_algo:
                if self._cur.get("title") and self._cur.get("url"):
                    self.results.append(dict(self._cur))
                self._in_algo = False
                self._state   = None
                self._cur     = {}
            elif self._state == "title" and tag == "a":
                self._cur["title"] = "".join(self._buf).strip()
                self._state = "h2"
                self._buf   = []
            elif self._state == "h2" and tag == "h2":
                self._state = None
            elif self._state == "snippet" and tag == "p":
                self._cur["snippet"] = "".join(self._buf).strip()
                self._state = None
                self._buf   = []

        def handle_data(self, data):
            if self._state in ("title", "snippet"):
                self._buf.append(data)

    params = urllib.parse.urlencode({"q": query, "setlang": "zh-CN", "mkt": "zh-CN"})
    raw = _http_get(f"https://www.bing.com/search?{params}", use_proxy=False)
    html_text = raw.decode("utf-8", errors="replace")
    parser = _BingParser()
    parser.feed(html_text)
    items = [r for r in parser.results
             if r.get("title") and r.get("url")
             and "/aclick" not in r["url"]]
    return [{"title": _hl.unescape(r["title"]),
             "url":   r["url"],
             "snippet": _hl.unescape(r.get("snippet", ""))}
            for r in items[:max_results]]


def _search_baidu(query: str, max_results: int) -> list:
    """百度搜索（国内直连，中文内容最佳）"""
    import urllib.parse
    from html.parser import HTMLParser
    import html as _hl

    class _BaiduParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.results = []
            self._in_res  = False
            self._state   = None
            self._cur     = {}
            self._buf     = []

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            cls = d.get("class", "")
            # 结果块: <div class="result ...">
            if tag == "div" and "result" in cls and "result-op" not in cls:
                self._in_res = True
                self._cur = {}
            elif self._in_res and tag == "h3":
                self._state = "h3"
            elif self._state == "h3" and tag == "a":
                self._state = "title"
                self._cur["url"] = d.get("href", "")
                self._buf = []
            elif self._in_res and self._state is None:
                if tag == "div" and "c-abstract" in cls:
                    self._state = "snippet"
                    self._buf   = []

        def handle_endtag(self, tag):
            if tag == "div" and self._in_res and not self._state:
                if self._cur.get("title") and self._cur.get("url"):
                    self.results.append(dict(self._cur))
                self._in_res = False
                self._cur    = {}
            elif self._state == "title" and tag == "a":
                self._cur["title"] = "".join(self._buf).strip()
                self._state = "h3"
                self._buf   = []
            elif self._state == "h3" and tag == "h3":
                self._state = None
            elif self._state == "snippet" and tag == "div":
                self._cur["snippet"] = "".join(self._buf).strip()
                self._state = None
                self._buf   = []

        def handle_data(self, data):
            if self._state in ("title", "snippet"):
                self._buf.append(data)

    params = urllib.parse.urlencode({"wd": query, "ie": "utf-8"})
    raw = _http_get(
        f"https://www.baidu.com/s?{params}",
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        use_proxy=False
    )
    html_text = raw.decode("utf-8", errors="replace")
    parser = _BaiduParser()
    parser.feed(html_text)
    items = [r for r in parser.results if r.get("title") and r.get("url")]
    return [{"title": _hl.unescape(r["title"]),
             "url":   r["url"],
             "snippet": _hl.unescape(r.get("snippet", ""))}
            for r in items[:max_results]]


def _search_ddg(query: str, max_results: int) -> list:
    """DuckDuckGo HTML 搜索（走本地代理，用于国际内容）"""
    import urllib.parse
    from html.parser import HTMLParser
    import html as _hl

    class _DDGParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.results = []
            self._state  = None
            self._cur    = {}
            self._buf    = []

        def handle_starttag(self, tag, attrs):
            d   = dict(attrs)
            cls = d.get("class", "")
            if tag == "a" and "result__a" in cls:
                self._state = "title"
                self._cur   = {"url": d.get("href", "")}
                self._buf   = []
            elif tag == "a" and "result__snippet" in cls:
                self._state = "snippet"
                self._buf   = []

        def handle_endtag(self, tag):
            if tag == "a":
                if self._state == "title":
                    self._cur["title"] = "".join(self._buf).strip()
                    self._state = None
                elif self._state == "snippet":
                    self._cur["snippet"] = "".join(self._buf).strip()
                    if self._cur.get("title") and self._cur.get("url"):
                        self.results.append(dict(self._cur))
                        self._cur = {}
                    self._state = None

        def handle_data(self, data):
            if self._state:
                self._buf.append(data)

    params = urllib.parse.urlencode({"q": query})
    raw = _http_get(
        f"https://html.duckduckgo.com/html/?{params}",
        use_proxy=True   # DDG 在国内需要代理
    )
    html_text = raw.decode("utf-8", errors="replace")
    parser = _DDGParser()
    parser.feed(html_text)
    items = [r for r in parser.results if r.get("title") and r.get("url")]
    return [{"title": _hl.unescape(r["title"]),
             "url":   r["url"],
             "snippet": _hl.unescape(r.get("snippet", ""))}
            for r in items[:max_results]]


# ===== 工具函数 =====

def tool_web_search(query: str, max_results: int = 10, engine: str = "auto") -> str:
    """多引擎搜索：auto(必应→DDG) / bing(必应直连) / baidu(百度) / ddg(走代理)"""
    import time
    
    # 重试配置
    max_retries = 3
    retry_delay = 1  # 秒
    
    engines = {
        "bing":  ("Bing",  lambda: _search_bing(query, max_results)),
        "baidu": ("Baidu", lambda: _search_baidu(query, max_results)),
        "ddg":   ("DDG",   lambda: _search_ddg(query, max_results)),
    }

    if engine == "auto":
        # 策略：Bing 直连优先（国内可用）→ DDG 走代理（国际内容）
        order = [("Bing", lambda: _search_bing(query, max_results)),
                 ("DDG",  lambda: _search_ddg(query, max_results))]
    elif engine in engines:
        name, fn = engines[engine]
        order = [(name, fn)]
    else:
        return f"[error] 未知引擎: {engine}，可选 auto/bing/baidu/ddg"

    last_err = ""
    for eng_name, fn in order:
        for retry in range(max_retries):
            try:
                items = fn()
                if items:
                    return _fmt_results(query, items, eng_name)
                break  # 成功，跳出重试循环
            except Exception as e:
                last_err = f"{eng_name}: {e}"
                if retry < max_retries - 1:
                    time.sleep(retry_delay * (retry + 1))  # 指数退避
                    continue
                else:
                    break  # 重试次数用完，尝试下一个引擎
        else:
            continue  # 这个引擎失败，尝试下一个
        break  # 这个引擎成功，返回结果

    return f"(所有引擎均未返回结果。最后错误：{last_err})\n提示：若需访问国际网站，请确保代理软件（Clash/v2ray）正在运行。"
def _strip_html(html_text: str, max_lines: int = 500) -> str:
    """提取 HTML 纯文本，跳过 script/style/svg 等不可见标签"""
    from html.parser import HTMLParser
    import html as _hl

    class _Extractor(HTMLParser):
        SKIP  = {"script", "style", "head", "meta", "link", "noscript", "svg", "iframe"}
        BLOCK = {"p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                 "li", "tr", "td", "th", "article", "section", "header", "footer", "nav"}
        def __init__(self):
            super().__init__()
            self.parts = []
            self._skip = 0
        def handle_starttag(self, tag, attrs):
            if tag in self.SKIP:   self._skip += 1
            if tag in self.BLOCK:  self.parts.append("\n")
        def handle_endtag(self, tag):
            if tag in self.SKIP:   self._skip = max(0, self._skip - 1)
        def handle_data(self, data):
            if self._skip == 0:    self.parts.append(data)

    p = _Extractor()
    p.feed(html_text)
    raw = _hl.unescape("".join(p.parts))
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    return "\n".join(lines[:max_lines])


_url_cache: dict = {}        # url -> (timestamp, content)
_URL_CACHE_TTL = 300         # 5 分钟内同 URL 直接返回缓存


def _fetch_url_impl(url: str, max_chars: int = 8000, use_proxy: bool = False, is_retry: bool = False) -> str:
    """抓取网页的核心实现"""
    import httpx
    import chardet
    from urllib.parse import urlparse
    
    # 代理配置
    proxies = None
    if use_proxy or is_retry:
        # 尝试常见的代理端口
        proxy_ports = [7889, 7890, 7891, 10809, 10808, 1080]
        for port in proxy_ports:
            try:
                # 测试代理连接
                test_client = httpx.Client(proxies=f"http://127.0.0.1:{port}", timeout=5.0)
                test_response = test_client.get("http://httpbin.org/ip", timeout=5.0)
                if test_response.status_code == 200:
                    proxies = f"http://127.0.0.1:{port}"
                    break
            except:
                continue
    
    # 请求头
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
    
    # 创建客户端
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    client_params = {
        "headers": headers,
        "timeout": timeout,
        "follow_redirects": True,
    }
    
    if proxies:
        client_params["proxies"] = proxies
    
    try:
        with httpx.Client(**client_params) as client:
            response = get_client().get(url)
            response.raise_for_status()
            
            # 检测编码
            raw_content = response.content
            if not raw_content:
                return "[error] 网页内容为空"
            
            # 尝试多种编码方式
            encodings_to_try = []
            
            # 1. 从HTTP头获取
            content_type = response.headers.get("content-type", "")
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip().lower()
                encodings_to_try.append(charset)
            
            # 2. 从HTML meta标签获取
            try:
                # 提取前2000字节查找charset
                sample = raw_content[:2000].decode('ascii', errors='ignore')
                import re
                meta_charset = re.search(r"<meta[^>]*charset=[\"']?([^\"'>]+)", sample, re.I)
                if meta_charset:
                    encodings_to_try.append(meta_charset.group(1).lower())
            except:
                pass
            
            # 3. 常用编码
            encodings_to_try.extend(['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'iso-8859-1'])
            
            # 4. 使用chardet检测
            try:
                detected = chardet.detect(raw_content[:5000])
                if detected['confidence'] > 0.7:
                    encodings_to_try.insert(0, detected['encoding'])
            except:
                pass
            
            # 去重
            encodings_to_try = list(dict.fromkeys(encodings_to_try))
            
            # 尝试解码
            decoded_content = None
            for encoding in encodings_to_try:
                try:
                    decoded_content = raw_content.decode(encoding, errors='strict')
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            
            if decoded_content is None:
                # 最后尝试用errors='replace'
                decoded_content = raw_content.decode('utf-8', errors='replace')
            
            # 提取纯文本（简化版）
            import re
            # 移除脚本和样式
            decoded_content = re.sub(r'<script[^>]*>.*?</script>', '', decoded_content, flags=re.DOTALL | re.IGNORECASE)
            decoded_content = re.sub(r'<style[^>]*>.*?</style>', '', decoded_content, flags=re.DOTALL | re.IGNORECASE)
            # 移除HTML标签
            decoded_content = re.sub(r'<[^>]+>', ' ', decoded_content)
            # 合并多余空白
            decoded_content = re.sub(r'\s+', ' ', decoded_content)
            decoded_content = decoded_content.strip()
            
            # 截断到指定长度
            if max_chars > 0 and len(decoded_content) > max_chars:
                decoded_content = decoded_content[:max_chars] + "...[截断]"
            
            return decoded_content
            
    except httpx.TimeoutException:
        raise Exception("请求超时")
    except httpx.HTTPStatusError as e:
        raise Exception(f"HTTP错误 {e.response.status_code}: {e.response.reason_phrase}")
    except httpx.RequestError as e:
        raise Exception(f"请求失败: {e}")
    except Exception as e:
        raise Exception(f"未知错误: {e}")
def tool_fetch_url(url: str, max_chars: int = 8000, use_proxy: bool = False) -> str:
    """抓取任意网页纯文本，自动检测编码（GBK/UTF-8）。直连失败时自动走本地代理重试。use_proxy=true 可强制走代理（访问 Twitter/Reddit 等被封网站）。"""
    import time
    import httpx
    import chardet
    import re
    
    # 重试配置
    max_retries = 3
    retry_delay = 1  # 秒
    
    for retry in range(max_retries):
        try:
            # 代理配置
            proxies = None
            if use_proxy or retry > 0:
                # 尝试常见的代理端口
                proxy_ports = [7889, 7890, 7891, 10809, 10808, 1080]
                for port in proxy_ports:
                    try:
                        # 测试代理连接
                        test_client = httpx.Client(proxies=f"http://127.0.0.1:{port}", timeout=5.0)
                        test_response = test_client.get("http://httpbin.org/ip", timeout=5.0)
                        if test_response.status_code == 200:
                            proxies = f"http://127.0.0.1:{port}"
                            break
                    except:
                        continue
            
            # 请求头
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            }
            
            # 创建客户端
            timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
            client_params = {
                "headers": headers,
                "timeout": timeout,
                "follow_redirects": True,
            }
            
            if proxies:
                client_params["proxies"] = proxies
            
            with httpx.Client(**client_params) as client:
                response = get_client().get(url)
                response.raise_for_status()
                
                # 检测编码
                raw_content = response.content
                if not raw_content:
                    return "[error] 网页内容为空"
                
                # 尝试多种编码方式
                encodings_to_try = []
                
                # 1. 从HTTP头获取
                content_type = response.headers.get("content-type", "")
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip().lower()
                    encodings_to_try.append(charset)
                
                # 2. 从HTML meta标签获取
                try:
                    # 提取前2000字节查找charset
                    sample = raw_content[:2000].decode('ascii', errors='ignore')
                    meta_charset = re.search(r'<meta[^>]*charset=[""]?([^"">]+)', sample, re.I)
                    if meta_charset:
                        encodings_to_try.append(meta_charset.group(1).lower())
                except:
                    pass
                
                # 3. 常用编码
                encodings_to_try.extend(['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'iso-8859-1'])
                
                # 4. 使用chardet检测
                try:
                    detected = chardet.detect(raw_content[:5000])
                    if detected['confidence'] > 0.7:
                        encodings_to_try.insert(0, detected['encoding'])
                except:
                    pass
                
                # 去重
                encodings_to_try = list(dict.fromkeys(encodings_to_try))
                
                # 尝试解码
                decoded_content = None
                for encoding in encodings_to_try:
                    try:
                        decoded_content = raw_content.decode(encoding, errors='strict')
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                
                if decoded_content is None:
                    # 最后尝试用errors='replace'
                    decoded_content = raw_content.decode('utf-8', errors='replace')
                
                # 提取纯文本（简化版）
                # 移除脚本和样式
                decoded_content = re.sub(r'<script[^>]*>.*?</script>', '', decoded_content, flags=re.DOTALL | re.IGNORECASE)
                decoded_content = re.sub(r'<style[^>]*>.*?</style>', '', decoded_content, flags=re.DOTALL | re.IGNORECASE)
                # 移除HTML标签
                decoded_content = re.sub(r'<[^>]+>', ' ', decoded_content)
                # 合并多余空白
                decoded_content = re.sub(r'\s+', ' ', decoded_content)
                decoded_content = decoded_content.strip()
                
                # 截断到指定长度
                if max_chars > 0 and len(decoded_content) > max_chars:
                    decoded_content = decoded_content[:max_chars] + "...[截断]"
                
                return decoded_content
                
        except httpx.TimeoutException:
            if retry < max_retries - 1:
                time.sleep(retry_delay * (retry + 1))  # 指数退避
                continue
            else:
                return f"[error] 抓取失败（{max_retries}次重试）: 请求超时"
        except httpx.HTTPStatusError as e:
            if retry < max_retries - 1:
                time.sleep(retry_delay * (retry + 1))
                continue
            else:
                return f"[error] 抓取失败（{max_retries}次重试）: HTTP错误 {e.response.status_code}"
        except httpx.RequestError as e:
            if retry < max_retries - 1:
                time.sleep(retry_delay * (retry + 1))
                continue
            else:
                return f"[error] 抓取失败（{max_retries}次重试）: 请求失败: {e}"
        except Exception as e:
            if retry < max_retries - 1:
                time.sleep(retry_delay * (retry + 1))
                continue
            else:
                return f"[error] 抓取失败（{max_retries}次重试）: {type(e).__name__}: {e}"
    
    return f"[error] 抓取失败（{max_retries}次重试）: 未知错误"

def _encode_image(path: str) -> tuple:
    """返回 (mime_type, base64_data) - 修复版，确保兼容阿里云百炼API"""
    try:
        p = Path(path).expanduser().resolve()
        
        # 1. 检查文件是否存在
        if not p.exists():
            raise FileNotFoundError(f"图片文件不存在: {path}")
        
        # 2. 检查文件大小
        file_size = p.stat().st_size
        if file_size > 10 * 1024 * 1024:  # 10MB限制
            raise ValueError(f"图片文件过大 ({file_size//1024//1024}MB > 10MB)")
        
        # 3. 尝试用PIL打开和验证图片
        try:
            with Image.open(p) as img:
                # 获取原始格式
                original_format = img.format
                original_mode = img.mode
                original_size = img.size
                
                # 4. 转换为兼容格式（阿里云百炼最兼容JPEG和PNG）
                # 先转换为RGB模式（如果需要）
                if original_mode not in ['RGB', 'L']:
                    img = img.convert('RGB')
                
                # 5. 如果图片太大，进行缩放（阿里云可能有尺寸限制）
                max_dimension = 2048
                if max(original_size) > max_dimension:
                    ratio = max_dimension / max(original_size)
                    new_size = (int(original_size[0] * ratio), int(original_size[1] * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # 6. 保存为JPEG格式（兼容性最好）
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                
                # 7. 获取base64编码
                b64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
                mime_type = 'image/jpeg'
                
                return mime_type, b64_data
                
        except Exception as img_error:
            # PIL处理失败，回退到原始方法
            print(f"警告: PIL处理失败，使用原始方法: {img_error}")
            mime, _ = mimetypes.guess_type(str(p))
            if not mime or not mime.startswith("image/"):
                # 根据扩展名兜底
                ext = p.suffix.lower()
                mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".gif": "image/gif",
                        ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "image/jpeg")
            data = base64.b64encode(p.read_bytes()).decode("utf-8")
            return mime, data
            
    except Exception as e:
        # 如果所有方法都失败，抛出异常
        raise ValueError(f"图片编码失败: {type(e).__name__}: {e}")

def _clean_unicode_string(text: str) -> str:
    """
    清理字符串中的无效Unicode字符，防止JSON序列化错误。
    特别是处理孤立的代理对（lone surrogate）问题。
    """
    if not isinstance(text, str):
        return text
    
    import re
    
    # 第一步：移除孤立的代理对字符（U+D800 到 U+DFFF）
    cleaned = re.sub(r'[\ud800-\udfff]', '', text)
    
    # 第二步：移除可能存在的JSON转义序列中的孤立代理对
    # 匹配 \uD800-\uDFFF 范围内的转义序列
    cleaned = re.sub(r'\\u[dD][89aAbBcCdDeEfF][0-9a-fA-F]{2}', '', cleaned)
    
    # 第三步：尝试编码/解码以移除其他无效字符
    try:
        cleaned = cleaned.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    except:
        pass
    
    return cleaned

def _clean_message_content(content):
    """
    清理消息内容中的无效Unicode字符。
    支持字符串、字典、列表等多种格式。
    """
    if isinstance(content, str):
        return _clean_unicode_string(content)
    elif isinstance(content, dict):
        cleaned = {}
        for key, value in content.items():
            cleaned[key] = _clean_message_content(value)
        return cleaned
    elif isinstance(content, list):
        return [_clean_message_content(item) for item in content]
    else:
        return content

def _clean_message_for_json(message):
    """
    清理整个消息对象，确保它可以被安全地序列化为JSON。
    """
    if not isinstance(message, dict):
        return message
    
    cleaned = {}
    for key, value in message.items():
        if key == 'content':
            cleaned[key] = _clean_message_content(value)
        elif isinstance(value, (str, dict, list)):
            cleaned[key] = _clean_message_content(value)
        else:
            cleaned[key] = value
    
    return cleaned


def _estimate_tokens_for_messages(messages):
    """
    估算消息列表的总token数。
    简化估算：1 token ≈ 4字符（英文字符），中文字符 ≈ 1.3 token。
    返回总token数和各消息的token数。
    """
    if not messages:
        return 0, []
    
    message_tokens = []
    total_tokens = 0
    
    for msg in messages:
        # 将消息转换为JSON字符串进行估算
        try:
            msg_str = json.dumps(msg, ensure_ascii=False)
            # 估算token：英文字符 / 4 + 中文字符 * 1.3
            # 简单估算：总字符数 * 0.75（中英文混合）
            token_est = int(len(msg_str) * 0.75)
            message_tokens.append(token_est)
            total_tokens += token_est
        except Exception:
            # 如果序列化失败，使用保守估算
            message_tokens.append(1000)  # 保守估算
            total_tokens += 1000
    
    return total_tokens, message_tokens


def _truncate_messages_by_tokens(messages, max_tokens=120000, keep_system=True):
    """
    根据token限制截断消息历史。
    保留系统消息（如果keep_system=True）和最新的对话消息。
    """
    if not messages:
        return messages
    
    total_tokens, message_tokens = _estimate_tokens_for_messages(messages)
    
    # 如果总token数在限制内，直接返回
    if total_tokens <= max_tokens:
        return messages
    
    console.print(f"[yellow]⚠ 消息历史过大: {total_tokens} tokens > {max_tokens} tokens，正在截断...[/]")
    
    truncated = []
    truncated_tokens = 0
    
    # 首先保留系统消息（如果有且需要）
    if keep_system and messages and messages[0].get("role") == "system":
        truncated.append(messages[0])
        truncated_tokens += message_tokens[0]
        # 从原列表移除已添加的系统消息
        messages = messages[1:]
        message_tokens = message_tokens[1:]
    
    # 从最新消息开始添加，直到达到token限制
    for i in range(len(messages) - 1, -1, -1):
        if truncated_tokens + message_tokens[i] <= max_tokens:
            truncated.insert(0, messages[i])  # 保持时间顺序
            truncated_tokens += message_tokens[i]
        else:
            # 无法添加更多消息，添加摘要消息
            summary_msg = {
                "role": "system",
                "content": f"[系统] 消息历史已截断。原始对话有 {len(messages)} 条消息，约 {total_tokens} tokens。保留了最新的 {len(truncated)} 条消息，约 {truncated_tokens} tokens。"
            }
            if keep_system and truncated and truncated[0].get("role") == "system":
                # 合并到现有系统消息
                truncated[0]["content"] = summary_msg["content"] + "\n\n" + truncated[0]["content"]
            else:
                truncated.insert(0, summary_msg)
            break
    
    # 重新计算截断后的token数
    final_tokens, _ = _estimate_tokens_for_messages(truncated)
    console.print(f"[green]✅ 消息历史已优化: {total_tokens} → {final_tokens} tokens ({len(messages)} → {len(truncated)} 条消息)[/]")
    
    return truncated


def tool_view_image_local(path: str, question: str = "请详细描述这张图片的内容") -> str:
    """用 Qwen-VL（DashScope 国际区）分析图片，结果返回给 DeepSeek"""
    import time
    import os
    import hashlib
    import pickle
    import mimetypes
    from pathlib import Path
    
    start_time = time.time()
    
    # ===== 新增：文件类型检查（修复百炼API处理文档的问题）=====
    if not (path.startswith("http://") or path.startswith("https://")):
        # 支持的图片格式
        SUPPORTED_IMAGE_EXTENSIONS = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif',
            '.jfif', '.pjpeg', '.pjp', '.svg'
        }
        
        # 文档格式（需要特殊处理）
        DOCUMENT_EXTENSIONS = {
            '.docx', '.doc', '.pdf', '.txt', '.md', '.rtf', '.odt',
            '.ppt', '.pptx', '.xls', '.xlsx'
        }
        
        # 检查文件是否存在
        file_path = Path(path)
        if not file_path.exists():
            # 更新失败统计
            with _view_image_stats_lock:
                _view_image_stats["failures"] += 1
            return f"[error] view_image: 文件不存在: {path}"
        
        # 获取文件扩展名
        ext = file_path.suffix.lower()
        
        # 检查文件类型
        if ext in DOCUMENT_EXTENSIONS:
            # 更新失败统计
            with _view_image_stats_lock:
                _view_image_stats["failures"] += 1
            doc_types = {
                '.docx': 'Word文档', '.doc': 'Word文档',
                '.pdf': 'PDF文档', '.txt': '文本文件',
                '.md': 'Markdown文档', '.rtf': '富文本文档',
                '.odt': 'OpenDocument文本', '.ppt': 'PowerPoint演示文稿',
                '.pptx': 'PowerPoint演示文稿', '.xls': 'Excel表格',
                '.xlsx': 'Excel表格'
            }
            doc_name = doc_types.get(ext, ext[1:].upper() + '文档')
            return f"""[error] view_image: 这是{doc_name}，百炼API无法直接处理文档文件。

解决方案:
1. 使用文档分析功能（如有）
2. 将文档转换为图片格式（截图或导出为图片）
3. 支持的图片格式: JPEG, PNG, GIF, BMP, WebP, TIFF"""
        
        elif ext not in SUPPORTED_IMAGE_EXTENSIONS:
            # 尝试通过MIME类型判断
            mime_type, _ = mimetypes.guess_type(path)
            if mime_type and any(keyword in mime_type for keyword in ['document', 'pdf', 'text', 'msword', 'officedocument', 'presentation', 'spreadsheet']):
                # 更新失败统计
                with _view_image_stats_lock:
                    _view_image_stats["failures"] += 1
                return f"""[error] view_image: 这是文档文件({mime_type})，百炼API无法直接处理文档。

请将文档转换为图片格式或使用文档分析功能。"""
            elif not mime_type or not mime_type.startswith('image/'):
                # 更新失败统计
                with _view_image_stats_lock:
                    _view_image_stats["failures"] += 1
                return f"""[error] view_image: 不支持的文件类型: {ext} ({mime_type or '未知MIME类型'})

百炼API仅支持以下图片格式:
- JPEG/JPG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- BMP (.bmp)
- WebP (.webp)
- TIFF (.tiff, .tif)"""
    # ===== 文件类型检查结束 =====
    
    # 更新统计
    with _view_image_stats_lock:
        _view_image_stats["total"] += 1
    
    # 缓存设置
    CACHE_DIR = Path.home() / ".ds_cache" / "view_image"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_TTL = 3600  # 1小时缓存
    
    # 生成缓存键
    if path.startswith("http://") or path.startswith("https://"):
        cache_key = hashlib.md5(f"{path}:{question}".encode()).hexdigest()
    else:
        try:
            with open(path, "rb") as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
            cache_key = hashlib.md5(f"{file_hash}:{question}".encode()).hexdigest()
        except Exception:
            cache_key = None
    
    # 检查缓存
    if cache_key:
        cache_file = CACHE_DIR / f"{cache_key}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    cached_data = pickle.load(f)
                if time.time() - cached_data["timestamp"] < CACHE_TTL:
                    return f"[缓存] {cached_data['result']}"
            except Exception:
                pass  # 缓存读取失败，继续正常流程
    
    # 检查本地文件大小（如果适用）
    if not (path.startswith("http://") or path.startswith("https://")):
        try:
            file_size = os.path.getsize(path)
            if file_size > 10 * 1024 * 1024:  # 10MB限制
                # 更新失败统计
                with _view_image_stats_lock:
                    _view_image_stats["failures"] += 1
                return f"[error] view_image: 图片文件过大 ({file_size//1024//1024}MB > 10MB)，请压缩图片"
        except Exception:
            pass  # 文件大小检查失败不影响正常流程
    
    try:
        import httpx as _httpx
        import asyncio
        
        _transport = _httpx.HTTPTransport(retries=3)
        
        async def async_request():
            async with _httpx.AsyncClient(transport=_transport, timeout=_httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0), trust_env=False) as client:
                vision_client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL,
                                       http_client=client)
                
                if path.startswith("http://") or path.startswith("https://"):
                    img_content = {"type": "image_url", "image_url": {"url": path}}
                else:
                    mime, b64 = _encode_image(path)
                    data_url = f"data:{mime};base64,{b64}"
                    img_content = {"type": "image_url", "image_url": {"url": data_url}}
                
                resp = await vision_client.chat.completions.create(
                    model=VISION_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            img_content,
                        ]
                    }],
                    max_tokens=1500,
                )
                return resp.choices[0].message.content or "(模型返回空内容)"
        
        # 尝试异步请求
        try:
            result = asyncio.run(async_request())
        except Exception:
            # 异步失败，回退到同步请求
            vision_client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)
            
            if path.startswith("http://") or path.startswith("https://"):
                img_content = {"type": "image_url", "image_url": {"url": path}}
            else:
                mime, b64 = _encode_image(path)
                data_url = f"data:{mime};base64,{b64}"
                img_content = {"type": "image_url", "image_url": {"url": data_url}}
            
            resp = vision_client.chat.completions.create(
                model=VISION_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        img_content,
                    ]
                }],
                max_tokens=1500,
            )
            result = resp.choices[0].message.content or "(模型返回空内容)"
        
        elapsed = time.time() - start_time
        
        # 更新成功统计
        with _view_image_stats_lock:
            _view_image_stats["success"] += 1
            _view_image_stats["total_time"] += elapsed
        
        # 保存到缓存
        if cache_key:
            try:
                cache_data = {
                    "timestamp": time.time(),
                    "result": f"[Qwen-VL 视觉识别结果] (耗时{elapsed:.1f}秒)\n{result}"
                }
                with open(cache_file, "wb") as f:
                    pickle.dump(cache_data, f)
            except Exception:
                pass  # 缓存保存失败不影响正常流程
        
        return f"[Qwen-VL 视觉识别结果] (耗时{elapsed:.1f}秒)\n{result}"
        
    except Exception as e:
        elapsed = time.time() - start_time
        
        # 更新失败统计
        with _view_image_stats_lock:
            _view_image_stats["failures"] += 1
        
        error_msg = f"{type(e).__name__}: {e}"
        if "InvalidParameter" in error_msg or "cannot identify image file" in error_msg:
            error_msg = f"百炼API无法处理此文件格式。请确保文件是支持的图片格式(JPEG/PNG/GIF/BMP/WebP/TIFF)。原始错误: {error_msg}"
        
        return f"[error] view_image: {error_msg}"

def tool_view_image(path: str, question: str = "请详细描述这张图片的内容") -> str:
    """
    图片分析工具 - 自动选择最佳实现
    优先使用 Vision Analyzer 技能，失败时回退到内置实现
    """
    # 清理输入参数
    path = _clean_unicode_string(path) if path else path
    question = _clean_unicode_string(question) if question else question
    
    try:
        # 优先使用 Vision Analyzer 技能
        if VISION_ANALYZER_AVAILABLE:
            # 导入可能已经完成，但为了安全再次导入
            try:
                from vision_helper import tool_view_image as vision_tool_view_image
                result = vision_tool_view_image(path, question)
                # 清理返回结果
                return _clean_unicode_string(result) if result else result
            except ImportError:
                # 回退到内置实现
                pass
    except Exception as e:
        # Vision Analyzer 失败，回退到内置实现
        print(f"[warning] Vision Analyzer 失败，使用内置实现: {e}")
    
    # 使用内置实现
    result = tool_view_image_local(path, question)
    # 清理返回结果
    return _clean_unicode_string(result) if result else result

def tool_browser_control(action: str, url: str = "", identifier: str = "",
                          text: str = "", script: str = "", task: str = "",
                          selector: str = "", value: str = "",
                          key: str = "", fields: list = None,
                          save_screenshot: str = "", wait_until: str = "domcontentloaded",
                          timeout: int = 30, multiple: bool = False) -> str:
    """
    通过 BrowserWing HTTP API 控制 Chrome 浏览器（自动启动/重连）。

    action 完整列表（32个命令）：
      navigate    — 打开URL  (url)
      snapshot    — 获取页面语义树（先调用此获取 @e1 @e2 等元素ID）
      click       — 点击元素  (identifier: @e1 / CSS选择器 / 文字内容)
      type        — 输入文字  (identifier, text)
      press_key   — 按键      (key: Enter/Tab/Escape/ArrowDown等)
      select      — 下拉选择  (identifier, text: 选项文字)
      fill_form   — 批量填表  (fields: [{"name": "email", "value": "..."}])
      extract     — 提取数据  (selector, multiple: true/false)
      page_text   — 获取全页文字
      page_info   — 获取当前URL和标题
      screenshot  — 截图并保存 (save_screenshot: 保存路径)
      exec_js     — 执行JS    (script: "() => document.title")
      scroll      — 滚动到底部
      wait        — 等待元素  (identifier, text: visible/hidden/enabled)
      hover       — 悬停元素  (identifier)
      go_back     — 后退
      go_forward  — 前进
      reload      — 刷新页面
      tabs        — 标签管理  (text: list/new/switch/close, identifier: 标签序号)
      file_upload — 上传文件  (identifier, text: 文件路径)
      drag        — 拖拽      (identifier: 源元素, selector: 目标元素)
      handle_dialog — 处理弹窗 (text: accept/dismiss)
      console_messages — 获取控制台日志
      network_requests — 获取网络请求
      resize      — 调整窗口  (fields: [{"width":1920,"height":1080}])
      ai_explore  — AI自动探索 (task, url)
      help        — 显示帮助
      status      — 检查服务状态并重连
    """
    import urllib.request, urllib.error, json as _json, time as _time, subprocess as _sp, os

    BASE = "http://localhost:8080/api/v1"
    BW_EXE   = "D:/AI_browser/browserwing.exe"
    BW_CFG   = "D:/AI_browser/config.toml"
    BW_DIR   = "D:/AI_browser"

    def _req(method: str, path: str, body=None, timeout_s: int = 60) -> str:
        data = _json.dumps(body).encode() if body is not None else None
        req  = urllib.request.Request(
            BASE + path, data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method=method,
        )
        try:
            r   = urllib.request.urlopen(req, timeout=timeout_s)
            raw = r.read().decode("utf-8", errors="replace")
            return raw[:6000] if len(raw) > 6000 else raw
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")[:600]
            return f"[HTTP {e.code}] {body_text}"
        except Exception as e:
            return f"[network_error] {type(e).__name__}: {e}"

    def _is_chrome_broken(resp: str) -> bool:
        """检测 Chrome 连接是否已断开"""
        markers = ["browser connection is closed", "connection may be closed",
                   "closed network connection", "error.navigation"]
        return any(m in resp.lower() for m in markers)

    def _kill_bw():
        try:
            _sp.run(["taskkill", "/F", "/IM", "browserwing.exe"],
                    capture_output=True, timeout=5)
        except Exception:
            pass
        _time.sleep(1)

    def _start_bw() -> bool:
        os.makedirs(f"{BW_DIR}/logs", exist_ok=True)
        os.makedirs(f"{BW_DIR}/data", exist_ok=True)
        _sp.Popen(
            [BW_EXE, "--port", "8080", "--config", BW_CFG],
            cwd=BW_DIR,
            creationflags=_sp.CREATE_NO_WINDOW | _sp.DETACHED_PROCESS,
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
        )
        for _ in range(15):
            _time.sleep(1)
            try:
                urllib.request.urlopen("http://localhost:8080/health", timeout=2)
                return True
            except Exception:
                pass
        return False

    def _ensure_bw() -> tuple:
        """确保 BrowserWing 在线。返回 (ok: bool, msg: str)"""
        try:
            urllib.request.urlopen("http://localhost:8080/health", timeout=3)
            return True, "online"
        except Exception:
            pass
        console.print("[dim]◦ BrowserWing 未运行，正在自动启动…[/]")
        if _start_bw():
            return True, "started"
        return False, "failed"

    def _req_with_reconnect(method: str, path: str, body=None, timeout_s: int = 60) -> str:
        """执行请求，如果 Chrome 连接断开则自动重启 BrowserWing 后重试"""
        resp = _req(method, path, body, timeout_s)
        if _is_chrome_broken(resp):
            console.print("[dim yellow]⚠ Chrome 连接断开，正在重启 BrowserWing…[/]")
            _kill_bw()
            ok, _ = _ensure_bw()
            if not ok:
                return "[error] BrowserWing 重启失败，请手动运行: D:/AI_browser/browserwing.exe --port 8080"
            console.print("[dim]✓ BrowserWing 已重启，重试请求…[/]")
            resp = _req(method, path, body, timeout_s)
        return resp

    # ── 确保服务在线 ────────────────────────────────────────────────────────
    ok, status_msg = _ensure_bw()
    if not ok:
        return ("[error] BrowserWing 启动失败。\n"
                "请手动运行：D:/AI_browser/browserwing.exe --port 8080\n"
                "或检查 Chrome 是否已安装：C:/Program Files/Google/Chrome/Application/chrome.exe")

    a = action.lower().strip().replace("-", "_")
    # identifier 兼容旧参数名（ref / selector / value → identifier / text）
    _id  = identifier or selector or value or ""
    _txt = text or value or ""

    # ── 各 action 处理 ──────────────────────────────────────────────────────

    if a == "navigate":
        if not url:
            return "[error] navigate 需要 url 参数（如 url='https://www.baidu.com'）"
        body = {"url": url, "wait_until": wait_until, "timeout": timeout}
        res  = _req_with_reconnect("POST", "/executor/navigate", body, timeout_s=timeout + 30)
        return f"已导航到 {url}\n{res}"

    elif a == "snapshot":
        res = _req_with_reconnect("GET", "/executor/snapshot")
        # snapshot 很长时裁剪，优先保留元素树部分
        return res[:5000] + "\n…（已截断）" if len(res) > 5000 else res

    elif a in ("screenshot", "take_screenshot"):
        import base64
        res = _req_with_reconnect("POST", "/executor/screenshot",
                                   {"format": "png", "full_page": False})
        try:
            d   = _json.loads(res)
            b64 = d.get("data", d.get("screenshot", d.get("image", "")))
            if b64:
                save_path = save_screenshot or os.path.join(os.path.expanduser("~"), "Desktop", "screenshot.png")
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(b64))
                return f"截图已保存到 {save_path}"
        except Exception as e:
            pass
        return res

    elif a == "click":
        if not _id:
            return "[error] click 需要 identifier 参数（@e1 / CSS选择器 / 按钮文字）"
        return _req_with_reconnect("POST", "/executor/click",
                                    {"identifier": _id, "timeout": timeout})

    elif a == "type":
        if not _id:
            return "[error] type 需要 identifier 参数（输入框 @e3 / #input-id）"
        if not _txt:
            return "[error] type 需要 text 参数（要输入的文字）"
        return _req_with_reconnect("POST", "/executor/type",
                                    {"identifier": _id, "text": _txt, "clear": True})

    elif a in ("press_key", "presskey", "key"):
        k = key or _txt or "Enter"
        return _req_with_reconnect("POST", "/executor/press-key", {"key": k})

    elif a == "select":
        if not _id or not _txt:
            return "[error] select 需要 identifier 和 text（选项文字）"
        return _req_with_reconnect("POST", "/executor/select",
                                    {"identifier": _id, "value": _txt})

    elif a == "fill_form":
        fs = fields or []
        if not fs:
            return "[error] fill_form 需要 fields 参数：[{\"name\":\"email\",\"value\":\"...\"}]"
        return _req_with_reconnect("POST", "/executor/fill-form",
                                    {"fields": fs, "submit": False, "timeout": timeout})

    elif a == "extract":
        sel = _id or selector or ""
        if not sel:
            return "[error] extract 需要 selector（CSS选择器，如 '.result-item'）"
        return _req_with_reconnect("POST", "/executor/extract",
                                    {"selector": sel, "multiple": multiple,
                                     "fields": ["text", "href"]})

    elif a in ("page_text", "pagetext", "get_text"):
        return _req_with_reconnect("GET", "/executor/page-text")

    elif a in ("page_info", "pageinfo", "page_url"):
        return _req_with_reconnect("GET", "/executor/page-info")

    elif a in ("exec_js", "eval_js", "javascript"):
        if not script:
            return "[error] exec_js 需要 script 参数（JS代码，如 '() => document.title'）"
        return _req_with_reconnect("POST", "/executor/evaluate", {"script": script})

    elif a in ("scroll", "scroll_bottom", "scroll_to_bottom"):
        return _req_with_reconnect("POST", "/executor/scroll-to-bottom", {})

    elif a == "wait":
        if not _id:
            return "[error] wait 需要 identifier 参数"
        state = _txt or "visible"
        return _req_with_reconnect("POST", "/executor/wait",
                                    {"identifier": _id, "state": state, "timeout": timeout})

    elif a == "hover":
        if not _id:
            return "[error] hover 需要 identifier 参数"
        return _req_with_reconnect("POST", "/executor/hover", {"identifier": _id})

    elif a in ("go_back", "back"):
        return _req_with_reconnect("POST", "/executor/go-back", {})

    elif a in ("go_forward", "forward"):
        return _req_with_reconnect("POST", "/executor/go-forward", {})

    elif a == "reload":
        return _req_with_reconnect("POST", "/executor/reload", {})

    elif a == "tabs":
        tab_action = _txt or "list"
        body: dict = {"action": tab_action}
        if tab_action == "new" and url:
            body["url"] = url
        if tab_action in ("switch", "close") and _id:
            try:
                body["index"] = int(_id.replace("@e", "").strip())
            except Exception:
                body["index"] = 0
        return _req_with_reconnect("POST", "/executor/tabs", body)

    elif a in ("file_upload", "upload"):
        if not _id:
            return "[error] file_upload 需要 identifier（文件输入框）"
        paths = fields or ([_txt] if _txt else [])
        if not paths:
            return "[error] file_upload 需要 fields（文件路径列表）或 text（单个路径）"
        return _req_with_reconnect("POST", "/executor/file-upload",
                                    {"identifier": _id, "file_paths": paths})

    elif a == "drag":
        if not _id or not selector:
            return "[error] drag 需要 identifier（源）和 selector（目标）"
        return _req_with_reconnect("POST", "/executor/drag",
                                    {"from_identifier": _id, "to_identifier": selector})

    elif a in ("handle_dialog", "dialog"):
        accept = _txt.lower() != "dismiss"
        return _req_with_reconnect("POST", "/executor/handle-dialog",
                                    {"accept": accept, "text": text or ""})

    elif a in ("console_messages", "console"):
        return _req_with_reconnect("GET", "/executor/console-messages")

    elif a in ("network_requests", "network"):
        return _req_with_reconnect("GET", "/executor/network-requests")

    elif a == "resize":
        w = (fields[0].get("width", 1920) if fields else 1920)
        h = (fields[0].get("height", 1080) if fields else 1080)
        return _req_with_reconnect("POST", "/executor/resize", {"width": w, "height": h})

    elif a == "ai_explore":
        if not task:
            return "[error] ai_explore 需要 task 参数（自然语言任务描述）"
        body = {"task_desc": task, "start_url": url or "", "llm_config_id": "deepseek"}
        res  = _req_with_reconnect("POST", "/ai-explore/start", body)
        try:
            d   = _json.loads(res)
            sid = d.get("id", "")
            if sid:
                return (f"AI 探索已启动，session_id={sid}\n"
                        f"浏览器实时查看：http://localhost:8080\n"
                        f"查询状态：browser_control(action='snapshot')")
        except Exception:
            pass
        return res

    elif a == "status":
        try:
            urllib.request.urlopen("http://localhost:8080/health", timeout=3)
            snap = _req("GET", "/executor/page-info")
            return f"BrowserWing: ✓ 在线\n当前页面: {snap}"
        except Exception as e:
            return f"BrowserWing: ✗ 离线 ({e})\n运行: D:/AI_browser/browserwing.exe --port 8080"

    elif a == "help":
        return (
            "browser_control 完整 action 列表：\n"
            "  navigate(url)                  — 打开网址\n"
            "  snapshot()                     — 获取页面结构（先调用此获取 @e1 @e2 元素ID）\n"
            "  click(identifier)              — 点击（@e1 / CSS选择器 / 文字）\n"
            "  type(identifier, text)         — 输入文字\n"
            "  press_key(key)                 — 按键（Enter/Tab/Escape/ArrowDown）\n"
            "  select(identifier, text)       — 下拉选择\n"
            "  fill_form(fields=[...])        — 批量填表\n"
            "  extract(selector, multiple)    — 提取数据\n"
            "  page_text()                    — 获取全页文字\n"
            "  page_info()                    — 当前URL和标题\n"
            "  screenshot(save_screenshot)    — 截图\n"
            "  exec_js(script)               — 执行JavaScript\n"
            "  scroll()                       — 滚动到底部\n"
            "  wait(identifier, text=visible) — 等待元素\n"
            "  hover(identifier)              — 悬停\n"
            "  go_back() / go_forward() / reload()\n"
            "  tabs(text=list/new/switch/close)\n"
            "  ai_explore(task, url)          — AI自动完成任务\n"
            "  status()                       — 检查服务状态\n\n"
            "典型工作流：\n"
            "  1. navigate(url='...')\n"
            "  2. snapshot()  ← 获取 @e1 @e2 元素ID\n"
            "  3. click(identifier='@e1') 或 type(identifier='@e3', text='搜索词')\n"
            "  4. press_key(key='Enter')\n"
            "  5. snapshot() 或 extract(selector='.result')"
        )

    else:
        return (f"[error] 未知 action: '{a}'。\n"
                "调用 browser_control(action='help') 查看完整列表。")


def tool_memory_search(query: str, top_k: int = 5, memory_dir: str = "") -> str:
    """用 BM25 在 ds.py 的长期记忆（~/.ds_memory/）中快速检索相关信息。
    比 grep_files 更智能：分词后多关键词匹配，自动排序相关性。
    用于回答"你还记得...吗"、"之前说的xxx"等需要回忆记忆的场景。
    """
    import os, re, math
    from pathlib import Path

    ds_mem = Path(memory_dir) if memory_dir else Path.home() / ".ds_memory"
    if not ds_mem.exists():
        return f"[记忆目录不存在: {ds_mem}]"

    # 收集所有 .md 文件内容
    docs = []   # (filepath, content)
    for root, dirs, files in os.walk(ds_mem):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.md'):
                fp = Path(root) / f
                try:
                    text = fp.read_text(encoding='utf-8', errors='replace')
                    docs.append((str(fp.relative_to(ds_mem)), text))
                except Exception:
                    pass

    if not docs:
        return "[记忆目录为空，没有 .md 文件]"

    # 简单分词（中英文兼容）
    def tokenize(text: str):
        text = text.lower()
        # 英文单词 + 中文字符
        tokens = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]', text)
        return tokens

    # BM25 参数
    k1, b = 1.5, 0.75
    N = len(docs)
    corpus = [tokenize(content) for _, content in docs]
    avgdl = sum(len(d) for d in corpus) / N if N > 0 else 1

    # 统计 DF
    df = {}
    for doc_tokens in corpus:
        for t in set(doc_tokens):
            df[t] = df.get(t, 0) + 1

    def idf(term):
        n = df.get(term, 0)
        return math.log((N - n + 0.5) / (n + 0.5) + 1)

    # 查询分词
    query_tokens = tokenize(query)
    if not query_tokens:
        return "[查询词为空]"

    # 计算每篇文档的 BM25 分数
    scores = []
    for i, doc_tokens in enumerate(corpus):
        dl = len(doc_tokens)
        tf_map = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1
        score = 0.0
        for term in query_tokens:
            if term not in tf_map:
                continue
            tf = tf_map[term]
            score += idf(term) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        scores.append((scores.__len__(), score))
        scores[-1] = (i, score)

    # 排序取 top_k
    scores.sort(key=lambda x: x[1], reverse=True)
    top = [(docs[i][0], docs[i][1], s) for i, s in scores[:top_k] if s > 0]

    if not top:
        return f"[未找到与 '{query}' 相关的记忆]"

    # 格式化输出
    results = []
    for fname, content, score in top:
        # 提取包含查询词的上下文片段
        content_lower = content.lower()
        snippets = []
        for term in query_tokens:
            idx = content_lower.find(term)
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(content), idx + 120)
                snippet = content[start:end].replace('\n', ' ').strip()
                if snippet not in snippets:
                    snippets.append(f"...{snippet}...")
        snippet_text = '\n'.join(snippets[:2]) if snippets else content[:200]
        results.append(f"📄 {fname} (score={score:.2f})\n{snippet_text}")

    header = f"记忆检索结果（共 {len(docs)} 个文件，查询：'{query}'）\n{'='*50}\n"
    return header + "\n\n".join(results)


def tool_session_list() -> str:
    """列出所有在线的 DS 实例"""
    if not LIVE_DIR.exists():
        return "（无在线实例）"
    results = []
    for d in sorted(LIVE_DIR.iterdir()):
        if not d.is_dir():
            continue
        info_path = d / "info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            pid = info.get("pid", 0)
            alive = _session_pid_alive(pid)
            if not alive:
                continue  # 跳过僵尸注册
            inbox = d / "inbox.jsonl"
            unread = sum(1 for l in (inbox.read_text(encoding="utf-8").splitlines() if inbox.exists() else []) if l.strip())
            mark = "● " if d.name == _session_name else "  "
            results.append(f"{mark}[{d.name}]  PID:{pid}  启动:{info.get('started_at','')}  收件箱:{unread}条")
        except Exception:
            pass
    return ("在线实例：\n" + "\n".join(results)) if results else "（无在线实例）"


def tool_session_send(target: str, message: str) -> str:
    """向另一个 DS 实例的收件箱发送消息"""
    if not _session_name:
        return "[error] 当前实例未命名，请先用 /name <名字> 设置实例名"
    if target == _session_name:
        return "[error] 不能给自己发消息"
    target_dir = LIVE_DIR / target
    if not (target_dir / "info.json").exists():
        return f"[error] 目标实例 '{target}' 不存在或已离线"
    inbox_path = target_dir / "inbox.jsonl"
    msg = {
        "id": f"msg_{int(time.time()*1000)}",
        "from": _session_name,
        "message": message,
        "ts": datetime.now().strftime("%H:%M:%S"),
    }
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return f"✓ 已发送给 [{target}]"


def tool_session_recv(clear: bool = False) -> str:
    """读取当前实例收件箱中的所有消息。clear=True 则读后清空。"""
    global _inbox_read_pos
    if not _session_name:
        return "[error] 当前实例未命名"
    inbox_path = LIVE_DIR / _session_name / "inbox.jsonl"
    if not inbox_path.exists() or not inbox_path.read_text(encoding="utf-8").strip():
        return "（收件箱为空）"
    raw_lines = inbox_path.read_text(encoding="utf-8").splitlines()
    valid_lines = [l for l in raw_lines if l.strip()]
    msgs = []
    for line in valid_lines:
        try:
            m = json.loads(line)
            msgs.append(f"[{m.get('ts','')}] 来自 [{m.get('from','?')}]:\n  {m.get('message','')}")
        except Exception:
            pass
    if clear:
        inbox_path.write_text("", encoding="utf-8")
        _inbox_read_pos = 0
    else:
        _inbox_read_pos = len(raw_lines)  # 与 _check_inbox_notify 保持一致
    return (f"收件箱 ({len(msgs)} 条):\n\n" + "\n\n".join(msgs)) if msgs else "（收件箱为空）"


# =============================================================================
# ===== Agent 系统（Claude Code 架构移植）=====
# =============================================================================

# 自定义 Agent 定义目录（类比 Claude Code 的 .claude/agents/）
AGENTS_DIR = Path.home() / ".ds_agents"

def load_agent_definitions() -> dict:
    """
    从 ~/.ds_agents/ 加载自定义 Agent 定义（Markdown + YAML frontmatter）。
    内置三种：explore / plan / research
    """
    agents = {
        "explore": {
            "name": "explore",
            "description": "快速探索代码库：查找文件、搜索关键词、回答代码结构问题（只读）",
            "tools": ["read_file", "glob_files", "grep_files", "list_dir"],
            "system_prompt": (
                "你是一个专注于代码库探索的 Agent。"
                "只使用 read_file、glob_files、grep_files、list_dir 工具来回答问题，"
                "不要修改任何文件。快速、精准地找到所需信息，简洁地汇报结果。"
                "完成后调用 task_complete 返回结论。"
            ),
            "model": "chat",
        },
        "plan": {
            "name": "plan",
            "description": "软件架构规划：设计实现方案、分析权衡取舍、生成步骤计划（只读）",
            "tools": ["read_file", "glob_files", "grep_files", "list_dir"],
            "system_prompt": (
                "你是一个软件架构师 Agent。分析代码库结构，设计清晰的实现方案。"
                "只读取文件，不修改任何内容。"
                "输出详细的步骤计划：文件修改清单、实现顺序、潜在风险、预计工作量。"
                "完成后调用 task_complete 返回计划。"
            ),
            "model": "r1",
        },
        "research": {
            "name": "research",
            "description": "网络研究：搜索信息、抓取网页、分析资料，整理结构化报告",
            "tools": ["web_search", "fetch_url", "python_exec"],
            "system_prompt": (
                "你是一个网络研究 Agent。通过搜索和抓取网页来收集信息，"
                "整理成结构化报告。优先中文搜索，必要时也搜索英文资料。"
                "完成后调用 task_complete 返回研究报告。"
            ),
            "model": "chat",
        },
        "general": {
            "name": "general",
            "description": "通用 Agent：可使用全部工具完成任意子任务",
            "tools": ["*"],
            "system_prompt": (
                "你是一个通用 Sub-agent，拥有完整工具访问权限。"
                "专注完成分配给你的子任务，完成后调用 task_complete 返回结果。"
            ),
            "model": "chat",
        },
    }

    # 从用户目录加载自定义 Agent（支持 YAML frontmatter Markdown 格式）
    if AGENTS_DIR.exists():
        for md_file in AGENTS_DIR.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        fm_text = content[3:end].strip()
                        body = content[end + 3:].strip()
                        fm: dict = {}
                        for line in fm_text.splitlines():
                            if ":" in line:
                                k, v = line.split(":", 1)
                                v = v.strip().strip('"\'')
                                if v.startswith("["):
                                    fm[k.strip()] = [
                                        x.strip().strip('"\'')
                                        for x in v[1:-1].split(",") if x.strip()
                                    ]
                                else:
                                    fm[k.strip()] = v
                        name = fm.get("name", md_file.stem)
                        agents[name] = {
                            "name": name,
                            "description": fm.get("description", ""),
                            "tools": fm.get("tools", ["*"]),
                            "system_prompt": body,
                            "model": fm.get("model", "chat"),
                        }
            except Exception as e:
                console.print(f"[dim]⚠ 加载 Agent 失败 {md_file.name}: {e}[/]")

    return agents


# ===== edit_file 工具（Claude Code FileEditTool 移植）=====

def tool_edit_file(path: str, old_string: str, new_string: str,
                   replace_all: bool = False) -> str:
    """
    精确搜索-替换编辑文件（比 write_file 更安全）。
    old_string 必须在文件中唯一（否则报错要求提供更多上下文）。
    """
    try:
        p = Path(path)
        if not p.exists():
            return f"[error] 文件不存在: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_string)
        if count == 0:
            lines = content.splitlines()
            preview = "\n".join(f"{i+1:4}: {l}" for i, l in enumerate(lines[:30]))
            return (
                f"[error] 未找到要替换的字符串。\n"
                f"文件前30行：\n{preview}"
            )
        if not replace_all and count > 1:
            return (
                f"[error] 找到 {count} 个匹配，old_string 不唯一。\n"
                f"请在 old_string 中提供更多上下文行使其唯一，或设置 replace_all=true"
            )
        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        p.write_text(new_content, encoding="utf-8")
        verb = f"替换 {count} 处" if replace_all else "替换 1 处"
        return f"✓ {path}：{verb}"
    except Exception as e:
        return f"[error] edit_file: {e}"


# ===== todo_write 工具（Claude Code TodoWriteTool 移植）=====

_TODO_FILE = Path.home() / ".ds_todos.json"

def _load_todos() -> list:
    if _TODO_FILE.exists():
        try:
            return json.loads(_TODO_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_todos(todos: list):
    _TODO_FILE.write_text(
        json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def tool_todo_write(todos: list) -> str:
    """写入/更新任务追踪列表。每次传入完整数组（全量替换）。"""
    try:
        valid = []
        for t in todos:
            if isinstance(t, dict) and "content" in t:
                valid.append({
                    "id": str(t.get("id", len(valid) + 1)),
                    "content": t["content"],
                    "status": t.get("status", "pending"),
                    "priority": t.get("priority", "medium"),
                })
        _save_todos(valid)
        pending = sum(1 for t in valid if t["status"] == "pending")
        doing   = sum(1 for t in valid if t["status"] == "in_progress")
        done    = sum(1 for t in valid if t["status"] == "completed")
        return f"✓ 任务列表已更新：{len(valid)} 条（{doing} 进行中，{pending} 待办，{done} 已完成）"
    except Exception as e:
        return f"[error] todo_write: {e}"

def _show_todos():
    """显示当前任务列表（用于 /todo 命令）"""
    todos = _load_todos()
    if not todos:
        console.print("[dim]任务列表为空。使用 todo_write 工具或 /todo 命令管理任务。[/]")
        return
    icons    = {"pending": "○", "in_progress": "◐", "completed": "●"}
    colors   = {"high": "red", "medium": "yellow", "low": "dim", "": "white"}
    console.print(f"\n[bold]任务列表[/]  [dim]({len(todos)} 条)[/]\n")
    for t in todos:
        icon   = icons.get(t.get("status", "pending"), "○")
        color  = colors.get(t.get("priority", ""), "white")
        status = t.get("status", "pending")
        tid    = t.get("id", "?")
        text   = t.get("content", "")
        if status == "completed":
            console.print(f"  [dim]● [{tid}] {text} ✓[/]")
        elif status == "in_progress":
            console.print(f"  [cyan]◐ [{tid}] {text}[/]")
        else:
            console.print(f"  [{color}]{icon} [{tid}] {text}[/]")
    console.print()


# ===== ask_user 工具（Claude Code AskUserQuestionTool 移植）=====

def tool_ask_user(question: str, options: list = None) -> str:
    """
    占位实现：实际在 run_agent_stream 中被拦截处理。
    当 ask_user 出现在 tool_calls 批次中时，会暂停 Agent 循环等待用户回答。
    """
    return f"[ask_user pending] {question}"


# ===== spawn_subagent 工具（Claude Code AgentTool 移植）=====

def _run_subagent(messages: list, model: str, tools: list, max_rounds: int = 20,
                  agent_type: str = "general") -> str:
    """
    子 Agent 执行循环（非流式，使用独立对话上下文）。
    工具执行使用父级 TOOL_MAP，但不允许递归 spawn_subagent。
    """
    for round_n in range(1, max_rounds + 1):
        try:
            response = get_client().chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                stream=False,
            )
        except Exception as e:
            return f"[error] Sub-agent API 错误: {e}"

        msg        = response.choices[0].message
        content    = msg.content or ""
        tool_calls = getattr(msg, "tool_calls", None) or []

        # 记录 assistant 消息
        msg_dict: dict = {"role": "assistant", "content": content}
        if tool_calls:
            msg_dict["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls
            ]
        messages.append(_clean_message_for_json(msg_dict))

        if not tool_calls:
            return content or f"[Sub-agent {agent_type}] 未返回内容"

        # 处理工具调用
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments.strip() else {}
            except Exception:
                args = {}

            # task_complete → 提前退出
            if name == "task_complete":
                summary = args.get("summary", content or "完成")
                messages.append(_clean_message_for_json({"role": "tool", "tool_call_id": tc.id,
                                  "content": f"[task_complete] {summary}"}))
                return summary

            # 执行工具（阻止递归 spawn_subagent）
            if name == "spawn_subagent":
                result = "[error] Sub-agent 不能递归派生子 agent"
            else:
                fn = TOOL_MAP.get(name)
                if fn:
                    console.print(f"  [dim]◦ [{agent_type}:{name}] {str(args)[:80]}[/]")
                    try:
                        result = fn(**args)
                    except Exception as e:
                        result = f"[error] {e}"
                else:
                    result = f"[error] 工具 {name} 不可用"

            messages.append(_clean_message_for_json({"role": "tool", "tool_call_id": tc.id,
                              "content": str(result)[:8000]}))

    return f"[Sub-agent {agent_type}] 达到最大轮数 {max_rounds}，任务可能未完成"


def tool_spawn_subagent(description: str, prompt: str,
                         agent_type: str = "general",
                         model: str = None) -> str:
    """
    派生专用 Sub-agent 处理特定子任务（同步执行，阻塞直到完成）。
    参照 Claude Code AgentTool 架构设计。
    """
    agents = load_agent_definitions()
    agent_def = agents.get(agent_type, agents["general"])

    allowed_tools = agent_def.get("tools", ["*"])
    use_all = (allowed_tools == ["*"])

    # 为子 agent 构建工具列表（排除递归派生）
    excluded = {"task_complete", "spawn_subagent", "ask_user",
                "session_send", "session_recv", "session_list"}
    if use_all:
        sub_tools = [t for t in TOOLS if t["function"]["name"] not in excluded]
    else:
        sub_tools = [t for t in TOOLS
                     if t["function"]["name"] in allowed_tools
                     and t["function"]["name"] not in excluded]

    # 追加 task_complete（子 agent 用它退出）
    sub_tools = sub_tools + [{
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "子任务完成后调用此函数返回结果给父 Agent",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "任务结果摘要"}
                },
                "required": ["summary"]
            }
        }
    }]

    # 子 agent 系统提示
    sys_prompt = agent_def.get("system_prompt", "你是一个专用 Sub-agent。完成任务后调用 task_complete 返回结果。")
    sys_prompt += "\n\n**注意**：完成任务后必须调用 task_complete 工具，不要无限循环。"

    # 选择模型
    model_key  = model or agent_def.get("model", "chat")
    sub_model  = MODELS.get(model_key, MODELS["chat"])

    sub_messages = [
        {"role": "system",  "content": sys_prompt},
        {"role": "user",    "content": prompt},
    ]

    console.print(f"\n[cyan]◈ Sub-agent [{agent_type}][/]  [dim]{description}[/]")
    result = _run_subagent(sub_messages, sub_model, sub_tools,
                            max_rounds=20, agent_type=agent_type)
    console.print(f"[cyan]◈ Sub-agent [{agent_type}] 完成[/]\n")
    return result


TOOL_MAP = {
    "shell":            tool_shell,
    "shell_background": tool_shell_background,
    "shell_status":     tool_shell_status,
    "local_model":      tool_local_model,
    "read_file":     tool_read_file,
    "write_file":    tool_write_file,
    "list_dir":      tool_list_dir,
    "python_exec":   tool_python_exec,
    "web_search":    tool_web_search,
    "fetch_url":     tool_fetch_url,
    "glob_files":    tool_glob_files,
    "grep_files":    tool_grep_files,
    "view_image":    tool_view_image,
    "session_list":  tool_session_list,
    "session_send":  tool_session_send,
    "session_recv":  tool_session_recv,
    "memory_search":         tool_memory_search,
    "browser_control":       tool_browser_control,
    "solidworks_connect":    tool_solidworks_connect,
    "solidworks_disconnect": tool_solidworks_disconnect,
    "solidworks_info":       tool_solidworks_info,
    "solidworks_create_part": tool_solidworks_create_part,
    "solidworks_open_file":  tool_solidworks_open_file,
    "solidworks_create_gear": tool_solidworks_create_gear,
    "solidworks_batch":      tool_solidworks_batch,
    "solidworks_test":       tool_solidworks_test,
    "solidworks_help":       tool_solidworks_help,
    # ── Agent 系统新工具 ──
    "edit_file":             tool_edit_file,
    "spawn_subagent":        tool_spawn_subagent,
    "todo_write":            tool_todo_write,
    "ask_user":              tool_ask_user,
}

# ===== Agent 循环 =====

def _safe_call(fn, args: dict, name: str) -> str:
    """安全调用工具函数（带缓存和超时）"""
    return _safe_call_with_cache(fn, args, name)
def _fix_incomplete_assistant_messages(messages):
    """
    修复messages列表，确保没有不完整的assistant消息
    (assistant消息有tool_calls但没有对应的tool消息)
    返回修复后的messages列表
    """
    if not messages:
        return messages
    
    # 查找所有有tool_calls的assistant消息
    assistant_with_tool_calls = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            assistant_with_tool_calls.append(i)
    
    # 对于每个有tool_calls的assistant消息，检查是否有对应的tool消息
    for i in reversed(assistant_with_tool_calls):  # 从后往前处理
        assistant_msg = messages[i]
        tool_call_ids = [tc["id"] for tc in assistant_msg.get("tool_calls", [])]
        
        # 检查后续消息中是否有对应的tool消息
        found_tool_ids = set()
        for j in range(i + 1, len(messages)):
            if messages[j].get("role") == "tool":
                tool_call_id = messages[j].get("tool_call_id")
                if tool_call_id in tool_call_ids:
                    found_tool_ids.add(tool_call_id)
        
        # 如果缺少某些tool消息，则移除这个assistant消息及其后续的tool消息
        missing_tool_ids = set(tool_call_ids) - found_tool_ids
        if missing_tool_ids:
            # 移除从i开始的所有消息，直到下一个user或system消息
            to_remove = []
            for k in range(i, len(messages)):
                if messages[k].get("role") in ("user", "system"):
                    break
                to_remove.append(k)
            
            # 反向移除，避免索引问题
            for k in reversed(to_remove):
                messages.pop(k)
    
    return messages

# ── 生成中计时器（仿 Claude Code "* Thinking… (Xs)"）────────────────────────
class _Timer:
    """后台线程：* 脉冲闪烁（亮/暗交替），实时显示标签 + token 计数"""
    def __init__(self):
        self._stop = threading.Event()
        self._t = None
        self._label = "Generating…"
        self._tokens = 0
        self._lock = threading.Lock()

    def set_label(self, label: str):
        with self._lock:
            self._label = label

    def add_tokens(self, n: int):
        with self._lock:
            self._tokens += n

    def start(self):
        self._stop.clear()
        self._start = time.time()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        i = 0
        frames = ["\033[32;1m*\033[0m", "\033[32;2m*\033[0m"]
        while not self._stop.wait(0.5):
            elapsed = int(time.time() - self._start)
            star = frames[i % 2]
            with self._lock:
                label = self._label
                tokens = self._tokens
            tok_str = f" · ~{tokens} tok" if tokens > 0 else ""
            line = f"\r{star} \033[2m{label} ({elapsed}s){tok_str}\033[0m   "
            console.file.write(line)
            console.file.flush()
            i += 1

    def stop(self):
        self._stop.set()
        if self._t:
            self._t.join(0.6)
        console.file.write("\r" + " " * 50 + "\r")
        console.file.flush()

def run_agent_stream(messages: list, model: str, max_rounds: int = 1000) -> str:
    """流式 Agent 循环，仿 Claude Code 风格，支持 Ctrl+C 随时中断。"""
    
    # 验证和修复消息格式
    try:
        if not MessageHistoryFixer.validate_message_format(messages):
            _ibox.ensure_scroll_position()
            console.print("[API] 检测到消息格式问题，正在修复...")
            messages = MessageHistoryFixer.fix_message_sequence(messages)
    except Exception as e:
        _ibox.ensure_scroll_position()
        console.print(f"[API] 消息验证失败: {e}")
    
    # 强制再次修复，确保tool消息正确
    messages = MessageHistoryFixer.fix_message_sequence(messages)
    
    for round_n in range(1, max_rounds + 1):

        timer = _Timer()
        timer.start()

        # ── API 调用（指数退避重试 + 自动降级）────────────────────────────
        _max_api_retries = 3
        stream = None
        # 清理消息
        messages = [_clean_message_for_json(m) for m in messages]
        # 检查并截断消息历史（防止token超限）
        messages = _truncate_messages_by_tokens(messages, max_tokens=120000, keep_system=True)
        # 确定使用的模型（降级时自动切换）
        _actual_model = _api_router.current_model or model
        for _retry in range(_max_api_retries):
            try:
                _actual_model = _api_router.current_model or model
                api_start_time = time.time()
                stream = get_client().chat.completions.create(
                    model=_actual_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    stream=True,
                    stream_options={"include_usage": True},
                )
                api_response_time = time.time() - api_start_time
                _perf_monitor.record_api_time(api_response_time)
                break
            except Exception as e:
                _api_router.record_failure()
                if _retry < _max_api_retries - 1:
                    _wait = 2 ** _retry
                    # 降级后提示一次
                    if _api_router.is_fallback and _retry == 0:
                        console.print(f"[yellow]⚠ DeepSeek 不可用，切换到本地模型 ({_OLLAMA_MODEL})[/]")
                    else:
                        console.print(f"[yellow]⚠ API 错误（第{_retry+1}次），{_wait}s 后重试: {e}[/]")
                    time.sleep(_wait)
                else:
                    timer.stop()
                    console.print(f"[red]✗ API 错误（已重试 {_max_api_retries} 次）: {e}[/]")
                    raise

        content_parts: list = []
        tool_calls_raw: dict = {}
        reasoning_started = False
        reasoning_buf: list = []          # 收集完整推理内容
        reasoning_dots = 0                # 动态省略号计数
        content_started = False
        timer_stopped = False
        response_buf = ""
        live_ctx = None
        usage_info = None

        def _stop_timer_once():
            nonlocal timer_stopped
            if not timer_stopped:
                timer.stop()
                timer_stopped = True

        def _condense_reasoning(full_text: str) -> str:
            """
            将 R1 推理全文凝练成一句话（本地算法，零额外API调用）。
            策略：找最后一个含行动词的完整句子，截断到 90 字符。
            """
            if not full_text.strip():
                return "（推理完毕）"
            # 结论/行动关键词（按优先级排列）
            ACTION_WORDS = [
                "我将", "我会", "我来", "我打算", "我决定",
                "计划", "步骤", "首先", "应该", "需要",
                "所以", "因此", "总结", "结论", "最终",
                "方案", "策略", "目标",
            ]
            # 按句子切分（支持中英文标点）
            sents = re.split(r'[。！？\.\!\?]\s*', full_text)
            sents = [s.strip() for s in sents if len(s.strip()) > 6]
            # 从后往前找第一个含行动词的句子
            for s in reversed(sents):
                if any(w in s for w in ACTION_WORDS):
                    return (s[:90] + "…") if len(s) > 90 else s
            # 兜底：最后一行非空内容
            lines = [l.strip() for l in full_text.splitlines() if l.strip()]
            if lines:
                last = lines[-1]
                return (last[:90] + "…") if len(last) > 90 else last
            return full_text.strip()[:90]

        def _flush_reasoning():
            """推理结束时：清除实时点阵，打印凝练摘要"""
            nonlocal reasoning_started
            if not reasoning_started:
                return
            # 确保输出位置正确
            _ibox.ensure_scroll_position()
            # 清除当前行（点阵动画行）
            console.file.write("\r\033[2K")
            full = "".join(reasoning_buf)
            summary = _condense_reasoning(full)
            # 一行摘要：dim 蓝色 ◦ 图标
            console.file.write(f"\033[2m\033[38;2;80;180;255m◦ {summary}\033[0m\n")
            console.file.flush()
            reasoning_started = False

        # 确保输出位置在滚动区域底部
        _ibox.ensure_scroll_position()

        # ── 流式接收（含断线续传，最多续传 2 次）────────────────────────
        _stream_complete = False   # finish_reason == "stop"
        _max_stream_retries = 2
        _stream_attempt = 0

        try:
          while _stream_attempt <= _max_stream_retries:
            try:
                for chunk in stream:
                    # 检查ESC键是否被按下
                    if check_esc_key_pressed():
                        _stop_timer_once()
                        if response_buf:
                            console.file.write("\n")
                        console.print("[yellow]⏹  ESC键中断AI思考[/]")
                        raise EscInterrupt("ESC键中断AI思考")

                    # usage 在最后一个空 choices 的 chunk 里
                    if not chunk.choices:
                        if getattr(chunk, "usage", None):
                            usage_info = chunk.usage
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta

                    # 检测正常结束
                    if getattr(choice, "finish_reason", None) in ("stop", "tool_calls"):
                        _stream_complete = True

                    # R1 推理链
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        _stop_timer_once()
                        reasoning_buf.append(reasoning)
                        timer.add_tokens(max(1, len(reasoning) // 3))
                        if not reasoning_started:
                            reasoning_started = True
                        reasoning_dots += 1
                        if reasoning_dots % 30 == 1:
                            dots = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                            spin = dots[(reasoning_dots // 30) % len(dots)]
                            char_count = sum(len(s) for s in reasoning_buf)
                            console.file.write(f"\r\033[2m{spin} 深度思考中… ({char_count} 字)\033[0m")
                            console.file.flush()

                    # 回答正文
                    if delta.content:
                        _stop_timer_once()
                        if reasoning_started:
                            _flush_reasoning()
                        response_buf += delta.content
                        content_parts.append(delta.content)
                        timer.add_tokens(max(1, len(delta.content) // 3))

                    # 工具调用分片累积
                    if delta.tool_calls:
                        if reasoning_started:
                            _flush_reasoning()
                        for tc_chunk in delta.tool_calls:
                            idx = tc_chunk.index
                            if idx not in tool_calls_raw:
                                tool_calls_raw[idx] = {"id": "", "name": "", "args": ""}
                            if tc_chunk.id and not tool_calls_raw[idx]["id"]:
                                tool_calls_raw[idx]["id"] = tc_chunk.id
                            fn_name = getattr(tc_chunk.function, "name", None)
                            if fn_name and not tool_calls_raw[idx]["name"]:
                                tool_calls_raw[idx]["name"] = fn_name
                                timer.set_label(f"Calling {fn_name}…")
                            fn_args = getattr(tc_chunk.function, "arguments", None)
                            if fn_args:
                                tool_calls_raw[idx]["args"] += fn_args

                # for 循环正常结束——检查是否真的说完了
                if _stream_complete or tool_calls_raw:
                    _api_router.record_success()
                    break  # 正常完成，退出 while

                # 没有 finish_reason=stop 且有内容 → 说到一半断了
                if content_parts and not _stream_complete:
                    _stream_attempt += 1
                    if _stream_attempt > _max_stream_retries:
                        console.print("[yellow]⚠ 回答被截断，已达最大续传次数[/]")
                        break
                    console.print(f"[yellow]⚠ 流式中断，尝试续传（{_stream_attempt}/{_max_stream_retries}）…[/]")
                    _api_router.record_failure()
                    # 构造续传请求：把已有内容作为 assistant 消息，再追加续传指令
                    _partial = "".join(content_parts)
                    _resume_msgs = list(messages) + [
                        {"role": "assistant", "content": _partial},
                        {"role": "user", "content": "你的回答被网络中断了，请从断点处继续（不要重复已有内容）。"},
                    ]
                    _actual_model = _api_router.current_model or model
                    stream = get_client().chat.completions.create(
                        model=_actual_model,
                        messages=[_clean_message_for_json(m) for m in _resume_msgs],
                        tools=TOOLS,
                        tool_choice="auto",
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                    continue  # 回到 while 循环继续接收
                else:
                    break  # 空回答，不续传

            except (KeyboardInterrupt, EscInterrupt):
                raise
            except Exception as e:
                # 网络层断线
                _stream_attempt += 1
                _api_router.record_failure()
                if _stream_attempt > _max_stream_retries:
                    console.print(f"[yellow]⚠ 网络断线，已达最大续传次数: {e}[/]")
                    break
                console.print(f"[yellow]⚠ 网络断线，{2}s 后续传（{_stream_attempt}/{_max_stream_retries}）…[/]")
                time.sleep(2)
                _partial = "".join(content_parts)
                if _partial:
                    _resume_msgs = list(messages) + [
                        {"role": "assistant", "content": _partial},
                        {"role": "user", "content": "你的回答被网络中断了，请从断点处继续（不要重复已有内容）。"},
                    ]
                else:
                    _resume_msgs = messages
                _actual_model = _api_router.current_model or model
                stream = get_client().chat.completions.create(
                    model=_actual_model,
                    messages=[_clean_message_for_json(m) for m in _resume_msgs],
                    tools=TOOLS,
                    tool_choice="auto",
                    stream=True,
                    stream_options={"include_usage": True},
                )
                continue

        except KeyboardInterrupt as e:
            _stop_timer_once()
            if response_buf:
                console.file.write("\n")
            if isinstance(e, EscInterrupt):
                console.print("[yellow]⏹  ESC键中断[/]")
            else:
                console.print("[yellow]⏹  Ctrl+C中断[/]")
            raise

        finally:
            _stop_timer_once()
            if reasoning_started:
                _flush_reasoning()

        full_content = "".join(content_parts)

        # 混合渲染：表格用 rich.Table，其余用 Markdown
        if full_content.strip():
            _render_response(full_content)

        # 打印 token 用量
                # 打印 token 用量
        # 打印 token 用量
        if usage_info:
            p = getattr(usage_info, "prompt_tokens", "?")
            c = getattr(usage_info, "completion_tokens", "?")
            console.print(f"[dim]↳ 输入 {p} · 输出 {c} tokens[/]")
            
            # 记录token使用
            if p != "?" and c != "?":
                try:
                    prompt_tokens = int(p)
                    completion_tokens = int(c)
                    total_tokens = prompt_tokens + completion_tokens
                    
                    # 简单的效率计算
                    prompt_percentage = (prompt_tokens / total_tokens * 100) if total_tokens > 0 else 0
                    efficiency = 100 - abs(prompt_percentage - 65)  # 65%是理想输入占比
                    
                    # 显示效率信息
                    if total_tokens > 100:  # 只对较大的调用显示效率
                        efficiency_level = "优秀" if efficiency > 80 else "良好" if efficiency > 60 else "一般"
                        console.print(f"[dim]  效率: {efficiency:.0f}/100 ({efficiency_level}) | 输入占比: {prompt_percentage:.1f}%[/]")
                    
                    # 简单的会话统计
                    if not hasattr(add_simple_token_display, "session_stats"):
                        add_simple_token_display.session_stats = {
                            "total_calls": 0,
                            "total_tokens": 0,
                            "total_prompt": 0,
                            "total_completion": 0
                        }
                    
                    stats = add_simple_token_display.session_stats
                    stats["total_calls"] += 1
                    stats["total_tokens"] += total_tokens
                    stats["total_prompt"] += prompt_tokens
                    stats["total_completion"] += completion_tokens
                    
                    # 每5次调用显示统计
                    if stats["total_calls"] % 5 == 0:
                        avg_tokens = stats["total_tokens"] / stats["total_calls"]
                        avg_prompt = stats["total_prompt"] / stats["total_calls"]
                        avg_completion = stats["total_completion"] / stats["total_calls"]
                        
                        console.print(f"[dim]📊 会话统计: {stats['total_calls']}次调用, 总计{stats['total_tokens']} tokens")
                        console.print(f"[dim]📊 平均: {avg_tokens:.0f} tokens/次 ({avg_prompt:.0f}↑ {avg_completion:.0f}↓)[/]")
                        
                        # 成本估算（DeepSeek定价：$0.14/百万tokens）
                        cost = (stats["total_tokens"] / 1_000_000) * 0.14
                        console.print(f"[dim]💰 估算成本: ${cost:.4f}[/]")
                        
                except Exception:
                    pass  # token统计失败不影响主要功能

        # 记录 assistant 消息
        msg_dict: dict = {"role": "assistant", "content": full_content}
        if tool_calls_raw:
            msg_dict["tool_calls"] = [
                {"id": tool_calls_raw[i]["id"], "type": "function",
                 "function": {"name": tool_calls_raw[i]["name"],
                              "arguments": tool_calls_raw[i]["args"]}}
                for i in sorted(tool_calls_raw.keys())
            ]
        messages.append(_clean_message_for_json(msg_dict))

        if not tool_calls_raw:
            return full_content

        # ── 工具执行（支持并行）──────────────────────────────────────────────
        console.print()

        # 1. 解析所有 tool_call 的参数
        ordered: list = []
        for idx in sorted(tool_calls_raw.keys()):
            tc = tool_calls_raw[idx]
            name, args_str, tc_id = tc["name"], tc["args"], tc["id"]
            try:
                args = json.loads(args_str) if args_str.strip() else {}
            except json.JSONDecodeError:
                args = {}
            ordered.append((idx, tc_id, name, args))

        # 2. task_complete 优先处理（遇到立即返回）
        tc_entry = next(((tc_id, args) for _, tc_id, name, args in ordered if name == "task_complete"), None)
        if tc_entry is not None:
            tc_id_main, tc_args = tc_entry
            summary = tc_args.get("summary", "任务完成")
            console.print(f"[bold green]✓[/] [green]{summary}[/]")
            # 必须为批次中所有 tool_calls 都补充响应，否则下轮 API 会报 400
            for _, tc_id, name, args in ordered:
                if name == "task_complete":
                    messages.append(_clean_message_for_json({
                        "role": "tool", 
                        "tool_call_id": tc_id,
                        "content": f"[task_complete] {summary}"
                    }))
                else:
                    messages.append(_clean_message_for_json({
                        "role": "tool", 
                        "tool_call_id": tc_id,
                        "content": "[skipped: task_complete]"
                    }))
            return summary

        # 2b. ask_user 拦截：暂停 Agent 等待用户回答（Claude Code AskUserQuestionTool 模式）
        ask_entry = next(((tc_id, args) for _, tc_id, name, args in ordered if name == "ask_user"), None)
        if ask_entry is not None:
            ask_tc_id, ask_args = ask_entry
            question = ask_args.get("question", "请回答：")
            options  = ask_args.get("options", [])
            console.print()
            console.print(f"[bold cyan]? {question}[/]")
            if options:
                for i, opt in enumerate(options, 1):
                    console.print(f"  [cyan]{i}.[/] {opt}")
            try:
                user_answer = input("  [你的回答]> ").strip() or "（无回答）"
            except Exception:
                user_answer = "（无回答）"
            # 为批次中所有 tool_calls 补充响应
            for _, tc_id, name, args in ordered:
                if name == "ask_user":
                    messages.append(_clean_message_for_json({
                        "role": "tool", 
                        "tool_call_id": tc_id,
                        "content": user_answer
                    }))
                else:
                    messages.append(_clean_message_for_json({
                        "role": "tool", 
                        "tool_call_id": tc_id,
                        "content": "[skipped: ask_user is waiting]"
                    }))
            continue  # 继续下一轮（带用户回答）

        # 3. 显示所有待执行工具（顺序展示，执行并行）
        for _, _, name, args in ordered:
            _ui_tool_call(name, args)

        # 4. 并行执行（≥2 个工具时用线程池，单工具直接调用避免开销）
        result_map: dict = {}
        if len(ordered) > 1:
            console.print(f"[dim]  ↳ 并行执行 {len(ordered)} 个工具…[/]")
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=min(len(ordered), 8)) as pool:
                fut_to_idx = {
                    pool.submit(_safe_call, TOOL_MAP.get(name), args, name): (idx, tc_id)
                    for idx, tc_id, name, args in ordered
                }
                for fut in as_completed(fut_to_idx):
                    idx, tc_id = fut_to_idx[fut]
                    result_map[idx] = (tc_id, fut.result())
            elapsed = time.time() - t0
            console.print(f"[dim]  ↳ 全部完成 ({elapsed:.1f}s)[/]")
            
            # 记录每个工具的执行时间（简化：平均分配总时间）
            avg_tool_time = elapsed / len(ordered) if ordered else 0
            for _, _, name, _ in ordered:
                _perf_monitor.record_tool_time(name, avg_tool_time)
        else:
            idx, tc_id, name, args = ordered[0]
            t0_single = time.time()
            result_map[idx] = (tc_id, _safe_call(TOOL_MAP.get(name), args, name))
            elapsed_single = time.time() - t0_single
            _perf_monitor.record_tool_time(name, elapsed_single)

        # 5. 按原顺序展示结果并追加消息
        for idx, tc_id, name, args in ordered:
            _, result = result_map[idx]
            _ui_tool_result(result)
            messages.append(_clean_message_for_json({"role": "tool", "tool_call_id": tc_id, "content": result}))

    console.print(f"[yellow]⚠ 达到最大轮数 {max_rounds}，强制结束[/]")
    return "[max rounds reached]"

# ===== 响应渲染（Markdown + rich.Table 混合）=====

def _render_table(md_table: str):
    """将 Markdown 表格字符串渲染为 rich.Table（完整边框，每行分隔，对齐截图样式）"""
    lines = [l for l in md_table.strip().splitlines() if l.strip()]
    if len(lines) < 3:
        console.print(Markdown(md_table))
        return
    header_cells = [c.strip() for c in lines[0].strip('|').split('|')]
    # lines[1] 是 |---|---| 分隔行，跳过
    tbl = Table(
        box=rich.box.SQUARE,
        show_header=True,
        show_lines=True,
        header_style="",          # 不加粗，与数据行等重
        border_style="white",
        pad_edge=True,
        padding=(0, 1),
    )
    for h in header_cells:
        tbl.add_column(h, overflow="fold")
    for line in lines[2:]:
        if not line.strip():
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        while len(cells) < len(header_cells):
            cells.append("")
        tbl.add_row(*cells[:len(header_cells)])
    console.print(tbl)

def _render_response(text: str):
    """混合渲染响应：Markdown 表格 → rich.Table，其余 → Markdown，带代码差异高亮"""
    
    # === 代码差异高亮处理 ===
    # 自动识别原始代码（红色）和修改后代码（绿色）
    processed_text = text
    
    # 查找所有代码块
    code_block_pattern = r'(```(\w*)\n)(.*?)(\n```)'
    code_matches = list(re.finditer(code_block_pattern, processed_text, re.DOTALL))
    
    if len(code_matches) >= 2:
        # 分析每个代码块的上下文
        block_colors = []  # 存储每个代码块的颜色标记
        
        for match in code_matches:
            start = match.start()
            # 查看代码块前的文本（最多300字符）
            context_start = max(0, start - 300)
            context = processed_text[context_start:start]
            
            # 检查关键词
            color = None
            
            # 获取更精确的上下文（最近3行）
            lines_before = context.split('\n')
            recent_lines = lines_before[-3:] if len(lines_before) >= 3 else lines_before
            recent_context = '\n'.join(recent_lines)
            
            # 使用正则表达式精确匹配
            original_patterns = [
                r'原始代码[：:]\s*$',
                r'修改前[：:]\s*$',
                r'original code[：:]\s*$',
                r'before[：:]\s*$',
                r'original[：:]\s*$'
            ]
            
            for pattern in original_patterns:
                if re.search(pattern, recent_context):
                    color = 'red'
                    break
            
            if color is None:
                modified_patterns = [
                    r'修改后[：:]\s*$',
                    r'修改为[：:]\s*$',
                    r'modified[：:]\s*$',
                    r'after[：:]\s*$',
                    r'改进后[：:]\s*$',
                    r'修复后[：:]\s*$'
                ]
                
                for pattern in modified_patterns:
                    if re.search(pattern, recent_context):
                        color = 'green'
                        break
                block_colors.append(color)
        
        # 智能推断：如果有修复/改进上下文但无明确标记
        if all(c is None for c in block_colors):
            if any(word in text for word in ["修复", "改进", "修改", "fix", "improve", "modify"]):
                # 标记第一个为原始（红色），第二个为修改后（绿色）
                if len(block_colors) >= 2:
                    block_colors[0] = 'red'
                    block_colors[1] = 'green'
        
        # 从后向前替换代码块（避免索引变化）
        for i in range(len(code_matches) - 1, -1, -1):
            match = code_matches[i]
            color = block_colors[i]
            
            if color:
                lang = match.group(2) or ""
                code = match.group(3)
                replacement = f"```{lang}\n[{color}]{code}[/]\n```"
                processed_text = processed_text[:match.start()] + replacement + processed_text[match.end():]
    
    # === 原有的表格处理逻辑 ===
    table_re = re.compile(
        r'(?m)(^[ \t]*\|[^\n]+\|\n)(^[ \t]*\|[-:| ]+\|\n)((?:^[ \t]*\|[^\n]+\|\n)*)',
    )
    segments, prev = [], 0
    for m in table_re.finditer(processed_text):
        if m.start() > prev:
            segments.append(("md", processed_text[prev:m.start()]))
        segments.append(("table", m.group()))
        prev = m.end()
    if prev < len(processed_text):
        segments.append(("md", processed_text[prev:]))
    for seg_type, content in segments:
        if seg_type == "md":
            stripped = content.strip()
            if stripped:
                console.print(Markdown(stripped))
        else:
            _render_table(content)
def _print_logo():
    console.print(f"  [bold {_LB}]████[/]      [bold {_LB}]████[/]")
    console.print(f"[bold {_LB}]██[/][bold {_DB}]██████████████[/][bold {_LB}]██[/]")
    console.print(f"[bold {_LB}]██[/][bold {_DB}]██[/]    [bold {_DB}]██[/]    [bold {_DB}]██[/][bold {_LB}]██[/]")
    console.print(f"[bold {_LB}]██[/][bold {_DB}]██████████████[/][bold {_LB}]██[/]")
    console.print(f"  [bold {_LB}]████[/]      [bold {_LB}]████[/]")

def _ui_banner(model_key: str):
    mem_count = len([f for f in MEMORY_DIR.glob("*.md") if f.name != "MEMORY.md"]) if MEMORY_DIR.exists() else 0
    console.print()
    _print_logo()
    console.print()
    console.print(
        f"[bold #ff8800]DeepSeek Terminal[/]  [dim]v1.0[/]\n"
        f"[#44cc88]{MODELS.get(model_key, model_key)}[/]\n"
        f"[dim]{mem_count} memories · tools {len(TOOLS) - 1}[/]"
    )
    console.print()
    console.print("[dim]/model chat|r1  /memory  /forget <f>  /clear  /retry  /context  quit  "
                  "[bold white]Esc[/] 中断[/]")
    console.print("[dim]/plan <任务>  /agents  /todo  — Agent 系统[/]")
    console.print("[dim]/name <名>  /who  /inbox  /send <目标> <消息>  — 多实例协作[/]")
    console.print()
    _ui_status_bar()

# ── 工具调用（Claude Code 风格）────────────────────────────────────────────

def _ui_status_bar():
    """显示状态栏：网络状态 + 系统信息"""
    import time
    from datetime import datetime
    
    # 获取网络状态（仅在启用时显示）
    network_status = get_network_status() if NETWORK_MONITOR_ENABLED else ""
    
    # 获取当前时间
    current_time = datetime.now().strftime("%H:%M:%S")
    
    # 获取系统信息（简化版）
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        system_info = f"CPU: {cpu_percent:.0f}% | RAM: {memory_percent:.0f}%"
    except:
        system_info = "系统监控未启用"
    
    # 显示状态栏
    parts = []
    if network_status:
        parts.append(f"📡 {network_status}")
    parts.append(f"🖥️ {system_info}")
    parts.append(f"🕐 {current_time}")
    console.print(f"[dim]{' | '.join(parts)}[/]")
    console.print()

def _ui_tool_call(name: str, args: dict):
    # 确保输出位置正确
    _ibox.ensure_scroll_position()
    s = json.dumps(args, ensure_ascii=False)
    if len(s) > 100:
        s = s[:97] + "…"
    console.print(f"[bold {_LB}]●[/] [bold]{name}[/][dim]({s})[/]")

def _ui_tool_result(result: str):
    # 确保输出位置正确
    _ibox.ensure_scroll_position()
    if result.startswith("[error]") or result.startswith("[stderr]"):
        preview = result[:300]
        console.print(f"[dim]└[/] [red]{preview}[/]")
    else:
        preview = result[:200] + ("…" if len(result) > 200 else "")
        console.print(f"[dim]└ {preview}[/]", markup=False)

def _ui_thinking(thoughts: list):
    """展示 <THINK> 块（流式已显示，这里处理标签后的展示）"""
    if thoughts:
        # 确保输出位置正确
        _ibox.ensure_scroll_position()
        for t in thoughts:
            if t.strip():
                console.print(f"[dim italic]{t.strip()}[/]")

def _ui_user_echo(text: str):
    """
    在滚动区域内回显用户输入（灰色底色）。
    固定输入框模式下：用户已在底部固定行输入，after_read() 后光标已回到
    滚动区域，直接在此打印回显即可，无需 \\033[A 向上覆盖。
    
    增强功能：
    1. 多行粘贴折叠为 [Pasted ~N lines] 并显示预览
    2. 长路径折叠显示
    3. 图片路径标记 🖼️
    4. 区分图片路径和普通路径
    """
    # 确保输出位置正确
    _ibox.ensure_scroll_position()
    
    original_text = text
    lines = text.split('\n')
    num_lines = len(lines)
    
    # 第一步：检测是否为图片路径（基于原始单行文本）
    is_image_path = False
    if num_lines == 1:
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg', '.jfif', '.ico'}
        lower_text = original_text.lower()
        
        # 检查是否以图片扩展名结尾
        if any(lower_text.endswith(ext) for ext in image_extensions):
            is_image_path = True
        # 检查是否包含常见的图片路径模式（用于URL）
        elif any(f'.{ext}' in lower_text for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg']):
            # 例如 http://example.com/image.png?param=value
            is_image_path = True
    
    # 第二步：处理多行粘贴
    if num_lines > 4:
        # 显示前2行，省略号，最后1行作为预览
        preview_lines = []
        if num_lines > 0:
            preview_lines.append(lines[0])
        if num_lines > 1:
            preview_lines.append(lines[1])
        if num_lines > 3:
            preview_lines.append('...')
        if num_lines > 1:
            preview_lines.append(lines[-1])
        
        preview_text = '\n'.join(preview_lines)
        display_text = f"[Pasted ~{num_lines} lines]\n{preview_text}"
    elif num_lines > 1:
        # 2-4行，直接显示所有行
        display_text = text
    else:
        # 单行文本
        display_text = text
    
    # 第三步：折叠长路径（仅限单行文本）
    if num_lines == 1 and len(display_text) >= 80:
        # 检查是否为文件路径或URL
        if '/' in display_text or '\\' in display_text or ':' in display_text:
            import os
            from urllib.parse import urlparse
            
            # 处理URL
            # 处理可能的图片图标前缀
            has_icon = display_text.startswith('🖼️  ')
            clean_text = display_text[3:] if has_icon else display_text
            
            if clean_text.startswith(('http://', 'https://', 'ftp://')):
                try:
                    parsed = urlparse(clean_text)
                    netloc = parsed.netloc
                    # 合并路径和查询参数用于长度计算
                    full_path = parsed.path
                    if parsed.query:
                        full_path += '?' + parsed.query
                    
                    # 如果路径部分较长或整个URL超过70字符，进行折叠
                    if len(full_path) > 20 or len(clean_text) > 70:
                        # 提取文件名（如果有）
                        dirname, basename = os.path.split(parsed.path)
                        if basename:
                            # 显示协议、域名和文件名
                            folded = f"{parsed.scheme}://{netloc}/.../{basename}"
                            if parsed.query:
                                folded += '?...'  # 提示有查询参数
                        else:
                            # 没有文件名，只显示域名
                            folded = f"{parsed.scheme}://{netloc}/..."
                        
                        # 恢复图片图标
                        display_text = f"🖼️  {folded}" if has_icon else folded
                    else:
                        # 不需要折叠，但可能需要恢复图标
                        if has_icon:
                            display_text = f"🖼️  {clean_text}"
                except:
                    # URL解析失败，简单截断
                    truncated = clean_text[:70] + "..."
                    display_text = f"🖼️  {truncated}" if has_icon else truncated
            else:
                # 文件系统路径
                if '/' in display_text or '\\' in display_text:
                    # 移除可能的图片图标前缀
                    clean_text = display_text
                    if clean_text.startswith('🖼️  '):
                        clean_text = clean_text[3:]  # 移除图标和空格
                    
                    basename = os.path.basename(clean_text)
                    if basename and len(basename) < 50:
                        # 显示为 .../basename
                        folded = f".../{basename}"
                        # 恢复图片图标
                        if display_text.startswith('🖼️  '):
                            display_text = f"🖼️  {folded}"
                        else:
                            display_text = folded
                    else:
                        # 简单截断
                        truncated = clean_text[:70] + "..."
                        if display_text.startswith('🖼️  '):
                            display_text = f"🖼️  {truncated}"
                        else:
                            display_text = truncated
    
    # 第四步：添加图片标记（如果尚未添加）
    if is_image_path and num_lines == 1 and not display_text.startswith('🖼️'):
        display_text = f"🖼️  {display_text}"
    
    # \033[48;2;42;42;42m = bg #2a2a2a  \033[1m = bold  \033[97m = bright white
    console.file.write(f"\033[48;2;42;42;42m\033[1m\033[97m> {display_text}\033[K\033[0m\n")
    console.file.flush()

# ===== 主循环 =====

def main():
    # 启动 MCP Server（后台线程，不阻塞主界面）
    if MCP_SERVER_CONFIG["enabled"]:
        threading.Thread(target=start_mcp_server, daemon=True).start()

    _init_memory()
    # 后台预热：代理检测（首次搜索前已就绪，不阻塞启动）
    threading.Thread(target=_detect_local_proxy, daemon=True).start()
    # 网络监控默认关闭，用 /netmon 手动开启

    # ── 解析 --name 参数，自动注册实例 ──────────────────────────────────────
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--name", default="", help="实例名（多实例协作用）")
    args, _ = parser.parse_known_args()
    _auto_name = args.name or f"ds-{os.getpid() % 10000}"
    session_register(_auto_name)

    # ── 输入会话（ds_input 键盘库）────────────────────────────────
    try:
        from ds_input import create_input_session, EscInterrupt
        session = create_input_session(history_path=HISTORY_PATH)
        if not session.available:
            session = None
    except (ImportError, Exception):
        session = None
    model_key = "r1"
    _ui_banner(model_key)
    console.print(f"[dim]实例名: [bold cyan]{_session_name}[/bold cyan]  · /name <名> 可改名[/]\n")

    # ── 启动固定底部输入框（Claude Code 风格）──────────────────────────────
    _ibox.setup()

    messages = [{"role": "system", "content": _get_sys_prompt()}]

    while True:
        # 每次输入前检查收件箱新消息
        _check_inbox_notify()

        try:
            # 定位光标到输入行（底部固定区域）
            _ibox.before_read()
            if session is None:
                user_input = input('> ').strip()
            else:
                user_input = session.read('> ')
            # 清空输入行，光标归还滚动区域
            _ibox.after_read()
        except EOFError:
            session_deregister()
            graceful_exit(messages, model_key)
            break
        except KeyboardInterrupt as e:
            if isinstance(e, EscInterrupt):
                console.print("[yellow]⏹  ESC键中断[/]")
            else:
                console.print("[yellow]⏹  Ctrl+C中断[/]")
            session_deregister()
            graceful_exit(messages, model_key)
            break

        if not user_input:
            continue

        # ── 退出 ──────────────────────────────────────────────────────────────
        if user_input.lower() in ("quit", "exit", "q"):
            session_deregister()
            graceful_exit(messages, model_key)
            break

        # ── 网络监控开关 ────────────────────────────────────────────────────
        if user_input == "/netmon":
            global NETWORK_MONITOR_ENABLED
            if not _NETWORK_MONITOR_AVAILABLE:
                console.print("[red]网络监控模块未安装[/]")
            elif NETWORK_MONITOR_ENABLED:
                stop_network_monitoring()
                NETWORK_MONITOR_ENABLED = False
                console.print("[dim]📡 网络监控已关闭[/]")
            else:
                start_network_monitoring()
                NETWORK_MONITOR_ENABLED = True
                console.print("[dim]📡 网络监控已开启[/]")
            continue

        # ── 模型切换 ──────────────────────────────────────────────────────────
        if user_input.startswith("/model "):
            new_key = user_input.split()[1]
            if new_key in MODELS:
                model_key = new_key
                _ui_banner(model_key)
            else:
                console.print(f"[red]未知模型: {new_key}[/]")
            continue

        # ── 查看记忆 ──────────────────────────────────────────────────────────
        if user_input == "/memory":
            show_memories()
            continue

        # ── 历史会话 ──────────────────────────────────────────────────────────
        if user_input == "/sessions":
            console.print(Panel(list_sessions(), title="[cyan]历史会话[/]", border_style="cyan"))
            continue
        # ── 网络状态 ──────────────────────────────────────────────────────────
        if user_input == "/network":
            console.print(Panel(get_network_details(), title="[cyan]网络状态详情[/]", border_style="cyan"))
            continue


        # ── 多实例：命名 ──────────────────────────────────────────────────────
        if user_input.startswith("/name "):
            new_name = user_input[6:].strip()
            if new_name:
                session_register(new_name)
                console.print(f"[cyan]✓ 实例名已设为: [bold]{_session_name}[/bold][/]")
            else:
                console.print("[red]用法: /name <名字>[/]")
            continue

        # ── 多实例：查看在线实例 ──────────────────────────────────────────────
        if user_input == "/who":
            console.print(Panel(tool_session_list(), title="[cyan]在线实例[/]", border_style="cyan"))
            continue

        # ── 多实例：查看收件箱 ────────────────────────────────────────────────
        if user_input in ("/inbox", "/inbox clear"):
            do_clear = user_input.endswith("clear")
            console.print(Panel(tool_session_recv(clear=do_clear),
                                title="[cyan]收件箱[/]", border_style="cyan"))
            continue

        # ── 多实例：快捷发送 ──────────────────────────────────────────────────
        if user_input.startswith("/send "):
            parts = user_input[6:].strip().split(" ", 1)
            if len(parts) == 2:
                result = tool_session_send(parts[0], parts[1])
                console.print(f"[cyan]{result}[/]")
            else:
                console.print("[red]用法: /send <目标实例名> <消息内容>[/]")
            continue

        # ── 删除记忆 ──────────────────────────────────────────────────────────
        if user_input.startswith("/forget "):
            fname = user_input[8:].strip()
            delete_memory(fname)             # 内部已设 _sp_cache["dirty"]
            messages[0] = {"role": "system", "content": _get_sys_prompt()}
            continue

        # ── 清空会话（保留系统提示）────────────────────────────────────────────
        if user_input == "/clear":
            messages = [messages[0]]
            console.print("[dim]✓ 会话已清空（记忆保留）[/]")
            continue

        # ── 上下文状态 ────────────────────────────────────────────────────────
        if user_input == "/context":
            n = len([m for m in messages if m["role"] != "system"])
            est = int(sum(len(str(m.get("content", ""))) for m in messages) / 3)
            proxy = _detect_local_proxy()
            mem_n = len([f for f in MEMORY_DIR.glob("*.md") if f.name != "MEMORY.md"]) if MEMORY_DIR.exists() else 0
            console.print(
                f"[dim]消息: {n} 条  |  估算上下文: ~{est:,} tokens  |  "
                f"记忆: {mem_n} 条  |  代理: {proxy if proxy else '直连'}[/]"
            )
            continue

        # ── 重试上一条 ────────────────────────────────────────────────────────
        if user_input == "/retry":
            # 移除最后一轮 assistant/tool 消息，重跑最后一条 user 消息
            while len(messages) > 1 and messages[-1]["role"] in ("assistant", "tool"):
                messages.pop()
            if len(messages) > 1 and messages[-1]["role"] == "user":
                last_content = messages[-1].get("content", "")
                echo_text = last_content if isinstance(last_content, str) else "(图片消息)"
                console.print(f"[dim]↺ 重试: {str(echo_text)[:80]}[/]")
                try:
                    raw_answer = run_agent_stream(messages, MODELS[model_key])
                except KeyboardInterrupt as e:
                    if isinstance(e, EscInterrupt):
                        console.print("\n[yellow]⏹  ESC键中断[/]\n")
                    else:
                        console.print("\n[yellow]⏹  Ctrl+C中断[/]\n")
                    continue
                no_think, thoughts = extract_think_blocks(raw_answer)
                _ui_thinking(thoughts)
                clean_answer = extract_and_save_memories(no_think)
            if messages and messages[-1]["role"] == "assistant":
                messages[-1]["content"] = _clean_unicode_string(clean_answer)
            if _sp_cache["dirty"]:
                messages[0] = _clean_message_for_json({"role": "system", "content": _get_sys_prompt()})
                if len(messages) > 100:
                    messages = compress_context(messages, MODELS[model_key], keep_recent=60)
            else:
                console.print("[dim]没有可重试的消息[/]")
            continue

        # ── /plan：规划模式（先出计划，用户确认后再执行）──────────────────────
        if user_input == "/plan" or user_input.startswith("/plan "):
            plan_task = user_input[5:].strip()
            if not plan_task:
                console.print("[dim]用法: /plan <任务描述>  或  /plan 后回车输入[/]")
                try:
                    plan_task = (session.read("[plan]> ") if session else input("[plan]> ").strip())
                except Exception:
                    continue
            if not plan_task:
                continue
            plan_prompt = (
                f"请为以下任务制定详细执行计划：\n\n{plan_task}\n\n"
                "**要求**：\n"
                "1. 用有序列表列出所有步骤\n"
                "2. 每步说明：做什么、用哪个工具、预期产出\n"
                "3. 标注潜在风险和注意事项\n"
                "4. **只生成计划，不执行任何操作**\n\n"
                "计划生成后，用户确认后我才会开始执行。"
            )
            _ui_user_echo(f"[规划] {plan_task}")
            messages.append(_clean_message_for_json({"role": "user", "content": plan_prompt}))
            try:
                raw_answer = run_agent_stream(messages, MODELS[model_key])
            except KeyboardInterrupt as e:
                if isinstance(e, EscInterrupt):
                    console.print("\n[yellow]⏹  ESC键中断[/]\n")
                else:
                    console.print("\n[yellow]⏹  Ctrl+C中断[/]\n")
                if messages and messages[-1]["role"] == "user":
                    messages.pop()
                continue
            no_think, thoughts = extract_think_blocks(raw_answer)
            _ui_thinking(thoughts)
            clean_answer = extract_and_save_memories(no_think)
            if messages and messages[-1]["role"] == "assistant":
                messages[-1]["content"] = _clean_unicode_string(clean_answer)
            if _sp_cache["dirty"]:
                messages[0] = _clean_message_for_json({"role": "system", "content": _get_sys_prompt()})
            console.print("\n[cyan dim]计划已生成。直接输入指令执行，或 /clear 放弃。[/]\n")
            continue

        # ── /agents：列出可用 Agents ───────────────────────────────────────────
        if user_input == "/agents":
            agents = load_agent_definitions()
            console.print("\n[bold cyan]可用 Sub-agents[/]  "
                          f"[dim](自定义目录: {AGENTS_DIR})[/]\n")
            for a_name, a_def in agents.items():
                tools_list = a_def.get("tools", ["*"])
                tools_str  = ", ".join(tools_list[:4])
                if len(tools_list) > 4:
                    tools_str += f" +{len(tools_list)-4}个"
                elif tools_list == ["*"]:
                    tools_str = "全部工具"
                console.print(
                    f"  [bold cyan]{a_name:12}[/] {a_def.get('description', '')}  "
                    f"[dim]({a_def.get('model','chat')} · {tools_str})[/]"
                )
            console.print(f"\n[dim]用法：让 DS 调用 spawn_subagent 工具，或输入 /plan 规划任务。[/]\n")
            continue

        # ── /todo：显示/清空任务列表 ──────────────────────────────────────────
        if user_input == "/todo":
            _show_todos()
            continue
        if user_input == "/todo clear":
            _save_todos([])
            console.print("[dim]✓ 任务列表已清空[/]")
            continue

        # ── 图片发送 ──────────────────────────────────────────────────────────
        if user_input.startswith("/image "):
            rest = user_input[7:].strip()
            if rest.startswith('"'):
                end_quote = rest.find('"', 1)
                if end_quote != -1:
                    img_path = rest[1:end_quote]
                    img_question = rest[end_quote+1:].strip() or "请详细描述这张图片的内容"
                else:
                    img_path = rest.strip('"')
                    img_question = "请详细描述这张图片的内容"
            else:
                parts = rest.split(" ", 1)
                img_path = parts[0]
                img_question = parts[1].strip() if len(parts) > 1 else "请详细描述这张图片的内容"

            try:
                if img_path.startswith("http://") or img_path.startswith("https://"):
                    img_content_block = {"type": "image_url", "image_url": {"url": img_path}}
                    console.print(f"[dim cyan]🖼  已附加图片URL: {img_path}[/]")
                else:
                    p_check = Path(img_path).expanduser()
                    if not p_check.exists():
                        console.print(f"[red]图片文件不存在: {img_path}[/]")
                        continue
                    mime, b64 = _encode_image(img_path)
                    data_url = f"data:{mime};base64,{b64}"
                    img_content_block = {"type": "image_url", "image_url": {"url": data_url}}
                    sz_kb = p_check.stat().st_size // 1024
                    console.print(f"[dim cyan]🖼  已附加图片: {img_path}  ({sz_kb}KB, {mime})[/]")

                multimodal_content = [
                    {"type": "text", "text": img_question},
                    img_content_block,
                ]
                _ui_user_echo(user_input)
                messages.append(_clean_message_for_json({"role": "user", "content": multimodal_content}))
            except Exception as e:
                console.print(f"[red]图片加载失败: {e}[/]")
                continue

            try:
                raw_answer = run_agent_stream(messages, MODELS[model_key])
            except KeyboardInterrupt as e:
                if isinstance(e, EscInterrupt):
                    console.print("\n[yellow]⏹  ESC键中断，继续输入新指令[/]\n")
                else:
                    console.print("\n[yellow]⏹  Ctrl+C中断，继续输入新指令[/]\n")
                if messages and messages[-1]["role"] == "user":
                    messages.pop()
                continue

            no_think, thoughts = extract_think_blocks(raw_answer)
            _ui_thinking(thoughts)
            clean_answer = extract_and_save_memories(no_think)
            if messages and messages[-1]["role"] == "assistant":
                messages[-1]["content"] = clean_answer
            if _sp_cache["dirty"]:
                messages[0] = _clean_message_for_json({"role": "system", "content": _get_sys_prompt()})
            if len(messages) > 220:
                messages = [messages[0]] + messages[-219:]
            continue

        # ── 普通对话 ──────────────────────────────────────────────────────────
        _ui_user_echo(user_input)
        messages.append(_clean_message_for_json({"role": "user", "content": user_input}))

        try:
            raw_answer = run_agent_stream(messages, MODELS[model_key])
        except KeyboardInterrupt as e:
            if isinstance(e, EscInterrupt):
                console.print("\n[yellow]⏹  ESC键中断，继续输入新指令[/]\n")
            else:
                console.print("\n[yellow]⏹  Ctrl+C中断，继续输入新指令[/]\n")
            # 修复不完整的assistant消息
            messages = _fix_incomplete_assistant_messages(messages)
            continue


        no_think, thoughts = extract_think_blocks(raw_answer)
        _ui_thinking(thoughts)
        clean_answer = extract_and_save_memories(no_think)
        if messages and messages[-1]["role"] == "assistant":
            messages[-1]["content"] = _clean_unicode_string(clean_answer)

        # 仅记忆变化时才重建系统提示（避免无意义磁盘 I/O）
        if _sp_cache["dirty"]:
            messages[0] = _clean_message_for_json({"role": "system", "content": _get_sys_prompt()})

        # 控制上下文长度
        if len(messages) > 100:
            messages = compress_context(messages, MODELS[model_key], keep_recent=60)



def show_view_image_stats() -> str:
    """显示 view_image 性能统计"""
    with _view_image_stats_lock:
        stats = _view_image_stats.copy()
    
    if stats["total"] == 0:
        return "view_image: 尚无统计信息"
    
    success_rate = (stats["success"] / stats["total"]) * 100
    avg_time = stats["total_time"] / stats["success"] if stats["success"] > 0 else 0
    
    return f"""view_image 性能统计:
总请求数: {stats["total"]}
成功: {stats["success"]} ({success_rate:.1f}%)
失败: {stats["failures"]}
总耗时: {stats["total_time"]:.1f}秒
平均耗时: {avg_time:.1f}秒"""

if __name__ == "__main__":
    main()





# ===== 测试函数 =====
def _test_lazy_client():
    """测试延迟客户端是否工作"""
    try:
        test_client = get_client()
        print("[测试] ✅ 延迟客户端初始化成功")
        return True
    except Exception as e:
        print(f"[测试] ❌ 延迟客户端初始化失败: {e}")
        return False

# 在main函数开始处调用测试
# 注意：这需要手动添加到main函数中