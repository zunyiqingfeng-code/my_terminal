#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Server 弹性池 — 按需启动，自动伸缩，空闲回收
启动时只起 1 个主实例（<0.3s），并发高时自动扩容，空闲自动缩容。
"""

import json
import time
import socket
import threading
import http.server
import socketserver
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


# ===== 兼容旧接口的枚举/配置（ds.py import 用） =====
class MCPMode(Enum):
    SINGLE = "single"
    CLUSTER = "cluster"

class LoadBalancingAlgorithm(Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    RANDOM = "random"


@dataclass
class MCPServerConfig:
    """MCP Server 配置（兼容旧字段 + 新弹性字段）"""
    enabled: bool = True
    mode: MCPMode = MCPMode.SINGLE       # 不再区分，统一弹性池
    host: str = "127.0.0.1"
    port: int = 3000                     # 主端口
    load_balancer_port: int = 3000       # 兼容旧配置
    max_workers: int = 5                 # 最大实例数
    scale_threshold: int = 3             # 并发请求 > 此值时扩容
    idle_timeout: int = 60               # 空闲 N 秒后回收多余实例
    # 兼容旧字段（不再使用）
    worker_ports: List[int] = field(default_factory=lambda: list(range(3001, 3011)))
    min_workers: int = 1
    health_check_interval: int = 30
    load_balancing_algorithm: LoadBalancingAlgorithm = LoadBalancingAlgorithm.ROUND_ROBIN


# ===== 端口工具 =====
def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_port(host: str, start: int, count: int = 1) -> List[int]:
    """从 start 开始找 count 个可用端口"""
    found = []
    for p in range(start, start + 100):
        if _port_available(host, p):
            found.append(p)
            if len(found) >= count:
                break
    return found


# ===== 单个 MCP 实例 =====
class _MCPInstance:
    def __init__(self, host: str, port: int, pool: "MCPServerPool"):
        self.host = host
        self.port = port
        self.pool = pool
        self._server = None
        self.running = False
        self.active_requests = 0
        self.total_requests = 0
        self.start_time = None
        self.last_active = time.time()

    def _handler_class(self):
        pool_ref = self.pool
        inst_ref = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                inst_ref.active_requests += 1
                inst_ref.total_requests += 1
                inst_ref.last_active = time.time()
                pool_ref._on_request()
                try:
                    if self.path == "/health":
                        body = {"status": "ok", "port": inst_ref.port}
                    elif self.path == "/stats":
                        body = pool_ref.get_stats()
                    else:
                        self.send_response(404)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(body, ensure_ascii=False).encode())
                finally:
                    inst_ref.active_requests -= 1

            def do_POST(self):
                inst_ref.active_requests += 1
                inst_ref.total_requests += 1
                inst_ref.last_active = time.time()
                pool_ref._on_request()
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    # MCP 协议处理预留
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode())
                finally:
                    inst_ref.active_requests -= 1

            def log_message(self, *a):
                pass
        return H

    def start(self):
        try:
            self._server = socketserver.ThreadingTCPServer(
                (self.host, self.port), self._handler_class()
            )
            self._server.daemon_threads = True
            self.running = True
            self.start_time = time.time()
            self._server.serve_forever()
        except Exception:
            self.running = False

    def start_bg(self) -> bool:
        if self.running:
            return True
        t = threading.Thread(target=self.start, daemon=True)
        t.start()
        # 快速轮询（最多 1 秒）
        for _ in range(10):
            time.sleep(0.1)
            if self.running:
                return True
        return False

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self.running = False


# ===== 弹性池 =====
class MCPServerPool:
    """
    按需弹性 MCP Server 池。
    - start() 只启动 1 个主实例
    - 并发高时 _on_request() 触发扩容
    - 后台 _scaler 线程定期回收空闲实例
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._instances: List[_MCPInstance] = []
        self._lock = threading.Lock()
        self.running = False
        self._scaler_thread = None

    def start(self) -> bool:
        if not self.config.enabled:
            return False
        host = self.config.host
        ports = _find_port(host, self.config.port, 1)
        if not ports:
            return False
        inst = _MCPInstance(host, ports[0], self)
        if inst.start_bg():
            self._instances.append(inst)
            self.running = True
            self.config.port = ports[0]  # 实际端口（可能被偏移）
            # 启动后台伸缩线程
            self._scaler_thread = threading.Thread(target=self._scaler, daemon=True)
            self._scaler_thread.start()
            return True
        return False

    def stop(self):
        self.running = False
        with self._lock:
            for inst in self._instances:
                inst.stop()
            self._instances.clear()

    def _on_request(self):
        """每次请求时检查是否需要扩容"""
        total_active = sum(i.active_requests for i in self._instances)
        n = len(self._instances)
        if total_active >= self.config.scale_threshold and n < self.config.max_workers:
            threading.Thread(target=self._scale_up, args=(1,), daemon=True).start()

    def _scale_up(self, count: int):
        with self._lock:
            n = len(self._instances)
            if n >= self.config.max_workers:
                return
            need = min(count, self.config.max_workers - n)
            used = {i.port for i in self._instances}
            start = max(used) + 1 if used else self.config.port + 1
            ports = _find_port(self.config.host, start, need)
            for p in ports:
                inst = _MCPInstance(self.config.host, p, self)
                if inst.start_bg():
                    self._instances.append(inst)

    def _scaler(self):
        """后台线程：每 10 秒检查，回收空闲超时的多余实例"""
        while self.running:
            time.sleep(10)
            if not self.running:
                break
            now = time.time()
            with self._lock:
                if len(self._instances) <= 1:
                    continue
                # 保留第一个（主实例），检查其余
                keep = [self._instances[0]]
                for inst in self._instances[1:]:
                    idle = now - inst.last_active
                    if idle > self.config.idle_timeout and inst.active_requests == 0:
                        inst.stop()
                    else:
                        keep.append(inst)
                self._instances = keep

    def get_stats(self) -> Dict[str, Any]:
        instances = {}
        for i, inst in enumerate(self._instances):
            iid = f"mcp-{i}" if i > 0 else "mcp-main"
            instances[iid] = {
                "host": inst.host,
                "port": inst.port,
                "running": inst.running,
                "active_requests": inst.active_requests,
                "total_requests": inst.total_requests,
                "uptime": time.time() - inst.start_time if inst.start_time else 0,
            }
        return {
            "running": self.running,
            "mode": "elastic",
            "total_instances": len(self._instances),
            "max_workers": self.config.max_workers,
            "instances": instances,
            "load_balancer_port": self.config.port,
        }


# ===== 兼容旧接口：MCPServerCluster =====
# ds.py 里 import MCPServerCluster / create_mcp_server_cluster
# 直接映射到 MCPServerPool

class MCPServerCluster(MCPServerPool):
    """兼容旧接口，内部使用弹性池"""
    pass


def create_mcp_server_cluster() -> MCPServerPool:
    config = MCPServerConfig(enabled=True, port=3000, max_workers=5)
    return MCPServerPool(config)


def start_mcp_server_improved():
    pool = create_mcp_server_cluster()
    if pool.start():
        return pool
    return None


# ===== 兼容旧导出 =====
PortManager = type("PortManager", (), {"__init__": lambda s, h="127.0.0.1": None})


def test_mcp_improvement():
    pool = create_mcp_server_cluster()
    if pool.start():
        print(f"OK: {pool.get_stats()}")
        time.sleep(2)
        pool.stop()
        return True
    return False


if __name__ == "__main__":
    test_mcp_improvement()
