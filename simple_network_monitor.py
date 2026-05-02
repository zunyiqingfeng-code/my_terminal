"""
简化版网络监控模块 - 不依赖外部库
"""

import threading
import time
import socket
import subprocess
import platform
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class NetworkStatus(Enum):
    """网络状态枚举"""
    EXCELLENT = "优秀"
    GOOD = "良好"
    FAIR = "一般"
    POOR = "较差"
    DISCONNECTED = "断开"


@dataclass
class NetworkMetrics:
    """网络指标数据类"""
    timestamp: datetime
    is_connected: bool
    latency_ms: float  # 延迟（毫秒）
    status: NetworkStatus
    test_server: str
    
    def __str__(self) -> str:
        if not self.is_connected:
            return "❌ 网络断开"
        
        status_emoji = {
            NetworkStatus.EXCELLENT: "🟢",
            NetworkStatus.GOOD: "🟡",
            NetworkStatus.FAIR: "🟠",
            NetworkStatus.POOR: "🔴",
            NetworkStatus.DISCONNECTED: "❌"
        }
        
        status_text = {
            NetworkStatus.EXCELLENT: "优秀",
            NetworkStatus.GOOD: "良好",
            NetworkStatus.FAIR: "一般",
            NetworkStatus.POOR: "较差"
        }
        
        return (
            f"{status_emoji[self.status]} "
            f"{status_text[self.status]} "
            f"({self.latency_ms:.0f}ms)"
        )


class SimpleNetworkMonitor:
    """简化版网络监控器"""
    
    def __init__(self, update_interval: int = 30):
        """
        初始化网络监控器
        
        Args:
            update_interval: 更新间隔（秒）
        """
        self.update_interval = update_interval
        self.metrics: Optional[NetworkMetrics] = None
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        
        # 测试服务器列表（按优先级排序）
        self.test_servers = [
            "8.8.8.8",      # Google DNS
            "1.1.1.1",      # Cloudflare DNS
            "114.114.114.114",  # 国内DNS
            "223.5.5.5",    # 阿里DNS
            "180.76.76.76", # 百度DNS
        ]
    
    def start(self) -> None:
        """启动监控线程"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="SimpleNetworkMonitor"
        )
        self._monitor_thread.start()
        print("✅ 网络监控已启动")
    
    def stop(self) -> None:
        """停止监控线程"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
    
    def _monitor_loop(self) -> None:
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                self._update_metrics()
            except Exception as e:
                print(f"⚠️ 网络监控更新失败: {e}")
            
            # 等待下一次更新
            for _ in range(self.update_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)
    
    def _update_metrics(self) -> None:
        """更新网络指标"""
        # 检查网络连接并测量延迟
        is_connected, latency_ms, test_server = self._check_connection_and_latency()
        
        if not is_connected:
            self.metrics = NetworkMetrics(
                timestamp=datetime.now(),
                is_connected=False,
                latency_ms=0,
                status=NetworkStatus.DISCONNECTED,
                test_server=""
            )
            return
        
        # 评估网络状态
        status = self._evaluate_status(latency_ms)
        
        self.metrics = NetworkMetrics(
            timestamp=datetime.now(),
            is_connected=True,
            latency_ms=latency_ms,
            status=status,
            test_server=test_server
        )
    
    def _check_connection_and_latency(self) -> Tuple[bool, float, str]:
        """检查连接并测量延迟"""
        best_latency = float('inf')
        best_server = ""
        is_connected = False
        
        for server in self.test_servers:
            try:
                # 方法1: 使用socket连接测试
                start_time = time.time()
                sock = socket.create_connection((server, 53), timeout=2)
                sock.close()
                latency = (time.time() - start_time) * 1000  # 转换为毫秒
                
                is_connected = True
                if latency < best_latency:
                    best_latency = latency
                    best_server = server
                    
            except (socket.timeout, ConnectionRefusedError, OSError):
                continue
        
        if not is_connected:
            # 方法2: 尝试ping命令（备用）
            try:
                ping_result = self._ping_test(self.test_servers[0])
                if ping_result[0]:  # 连接成功
                    is_connected = True
                    best_latency = ping_result[1]
                    best_server = self.test_servers[0]
            except:
                pass
        
        return is_connected, best_latency if best_latency != float('inf') else 999, best_server
    
    def _ping_test(self, host: str) -> Tuple[bool, float]:
        """使用ping命令测试连接"""
        try:
            # 根据操作系统选择ping命令参数
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            count = '2'  # ping 2次
            
            # 执行ping命令
            command = ['ping', param, count, '-w', '2000', host]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                # 解析ping结果获取延迟
                output = result.stdout
                lines = output.split('\n')
                
                for line in lines:
                    if '平均' in line or 'Average' in line or 'avg' in line.lower():
                        # 提取延迟数值
                        import re
                        match = re.search(r'(\d+\.?\d*)\s*ms', line)
                        if match:
                            latency = float(match.group(1))
                            return True, latency
                
                # 如果无法解析，返回默认值
                return True, 50.0
            else:
                return False, 999.0
                
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False, 999.0
    
    def _evaluate_status(self, latency_ms: float) -> NetworkStatus:
        """评估网络状态"""
        if latency_ms < 50:
            return NetworkStatus.EXCELLENT
        elif latency_ms < 100:
            return NetworkStatus.GOOD
        elif latency_ms < 200:
            return NetworkStatus.FAIR
        elif latency_ms < 500:
            return NetworkStatus.POOR
        else:
            return NetworkStatus.DISCONNECTED
    
    def get_status_string(self) -> str:
        """获取状态字符串"""
        if self.metrics is None:
            return "⏳ 网络监控初始化中..."
        return str(self.metrics)
    
    def get_detailed_info(self) -> str:
        """获取详细信息"""
        if self.metrics is None:
            return "网络监控未初始化"
        
        if not self.metrics.is_connected:
            return "❌ 网络连接已断开"
        
        return (
            f"📊 网络状态详情:\n"
            f"  状态: {self.metrics.status.value}\n"
            f"  延迟: {self.metrics.latency_ms:.1f} ms\n"
            f"  测试服务器: {self.metrics.test_server}\n"
            f"  更新时间: {self.metrics.timestamp.strftime('%H:%M:%S')}"
        )


# 全局监控器实例
_global_monitor: Optional[SimpleNetworkMonitor] = None


def get_network_monitor() -> SimpleNetworkMonitor:
    """获取全局网络监控器实例"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = SimpleNetworkMonitor(update_interval=30)
    return _global_monitor


def start_network_monitoring() -> None:
    """启动网络监控"""
    monitor = get_network_monitor()
    monitor.start()


def stop_network_monitoring() -> None:
    """停止网络监控"""
    global _global_monitor
    if _global_monitor:
        _global_monitor.stop()


def get_network_status() -> str:
    """获取网络状态字符串"""
    monitor = get_network_monitor()
    return monitor.get_status_string()


def get_network_details() -> str:
    """获取网络详细信息"""
    monitor = get_network_monitor()
    return monitor.get_detailed_info()


if __name__ == "__main__":
    # 测试网络监控
    print("🔧 测试简化版网络监控模块...")
    
    monitor = SimpleNetworkMonitor(update_interval=10)
    monitor.start()
    
    try:
        for i in range(5):
            print(f"\n📡 网络状态 ({i+1}/5):")
            print(f"  {monitor.get_status_string()}")
            time.sleep(2)
    finally:
        monitor.stop()
        print("\n✅ 网络监控测试完成")