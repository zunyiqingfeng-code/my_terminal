#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EnhancedAPIFixer - 智能API连接修复器
解决国内API连接问题，确保国内外都能连上
"""

import requests
import time
import socket
import threading
import httpx
from typing import Optional, Dict, Tuple
from openai import OpenAI

class EnhancedAPIFixer:
    """增强的API连接管理器，解决连接不稳定问题"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoints = [
            {"name": "global", "url": "https://api.deepseek.com", "priority": 1},
            {"name": "proxy", "url": "https://api.deepseek.com", "priority": 2},
        ]
        self.current_endpoint = None
        self.proxy_url = None
        self.client = None
        self.last_check_time = 0
        self.check_interval = 300  # 每5分钟检查一次连接
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
        proxy_ports = [10808, 7890, 7891, 10809, 1080, 1087]
        
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
        """创建HTTP客户端"""
        if not self.current_endpoint:
            self._select_best_endpoint()
        
        # 优化HTTP客户端配置
        http_client_kwargs = {
            "timeout": 60.0,  # 增加超时时间
            "limits": httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0
            ),
            "http2": True,  # 启用HTTP/2
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
            models = self.client.models.list()
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
        
        status_parts = []
        status_parts.append(f"当前端点: {self.current_endpoint['name']} ({self.current_endpoint['url']})")
        
        if self.proxy_url:
            status_parts.append(f"代理: {self.proxy_url}")
        
        if self.connection_stats["last_success"]:
            last_success = time.strftime("%H:%M:%S", time.localtime(self.connection_stats["last_success"]))
            status_parts.append(f"最后成功: {last_success}")
        
        if self.connection_stats["last_error"]:
            status_parts.append(f"最后错误: {self.connection_stats['last_error'][:50]}...")
        
        return "\n".join(status_parts)