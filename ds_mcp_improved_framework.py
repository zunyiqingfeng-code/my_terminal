#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DeepSeek Terminal 改进版 MCP Server 框架
这是 ds_mcp_improved_framework_fixed.py 的别名，用于兼容导入
"""

import sys
import os

# 将修复版框架作为主模块
from ds_mcp_improved_framework_fixed import *

# 确保所有导出都正确
__all__ = [
    'PortManager',
    'MCPServerConfig', 
    'MCPMode',
    'LoadBalancingAlgorithm',
    'MCPServerInstance',
    'MCPServerCluster',
    'create_mcp_server_cluster',
    'start_mcp_server_improved',
    'test_mcp_improvement'
]

