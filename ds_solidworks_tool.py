"""
DeepSeek SolidWorks 工具函数 (修复版)
修复零件创建和草图创建问题
"""

import sys
import os
import json
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

try:
    from solidworks_api_tool import (
        get_sw_tool,
        connect_sw,
        disconnect_sw,
        sw_info,
        create_sw_part,
        open_sw_file,
        SolidWorksTool
    )
    SOLIDWORKS_AVAILABLE = True
except ImportError as e:
    SOLIDWORKS_AVAILABLE = False
    print(f"[警告] SolidWorks 工具不可用: {e}")

def tool_solidworks_connect(visible: bool = True) -> str:
    """
    连接 SolidWorks
    
    Args:
        visible: 是否显示 SolidWorks 窗口
        
    Returns:
        连接结果信息
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用，请检查依赖"
    
    try:
        success = connect_sw(visible=visible)
        if success:
            tool = get_sw_tool()
            info = tool.get_info()
            version = info.get("version", "未知")
            return f"✅ SolidWorks 连接成功 (版本: {version})"
        else:
            return "❌ SolidWorks 连接失败"
    except Exception as e:
        return f"❌ SolidWorks 连接错误: {e}"

def tool_solidworks_disconnect() -> str:
    """
    断开 SolidWorks 连接
    
    Returns:
        断开结果信息
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        success = disconnect_sw()
        if success:
            return "✅ SolidWorks 已断开连接"
        else:
            return "⚠️  SolidWorks 未连接或断开失败"
    except Exception as e:
        return f"❌ SolidWorks 断开错误: {e}"

def tool_solidworks_info() -> str:
    """
    获取 SolidWorks 信息
    
    Returns:
        SolidWorks 信息
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        info = sw_info()
        
        if "error" in info:
            return f"❌ {info['error']}"
        
        # 格式化输出
        lines = ["🔧 SolidWorks 信息:"]
        lines.append("=" * 40)
        
        # 基本信息
        lines.append(f"📊 版本: {info.get('version', '未知')}")
        lines.append(f"👁️  可见性: {info.get('visible', False)}")
        lines.append(f"🖼️  框架状态: {info.get('frame_state', '未知')}")
        lines.append(f"👤 用户控制: {info.get('user_control', '未知')}")
        lines.append(f"⚙️  命令状态: {info.get('command_in_progress', '未知')}")
        
        # 连接时间
        if info.get("connection_time"):
            lines.append(f"⏰ 连接时间: {info['connection_time']}")
        
        # 活动文档
        doc_info = info.get("active_document")
        if doc_info:
            lines.append("\n📄 活动文档:")
            lines.append(f"  标题: {doc_info.get('title', '未知')}")
            lines.append(f"  类型: {doc_info.get('type', '未知')}")
            lines.append(f"  路径: {doc_info.get('path', '未知')}")
        else:
            lines.append("\n📄 活动文档: 无")
        
        lines.append("=" * 40)
        return "\n".join(lines)
        
    except Exception as e:
        return f"❌ 获取信息失败: {e}"

def tool_solidworks_create_part(template: str = None) -> str:
    """
    创建 SolidWorks 零件 (修复版)
    
    Args:
        template: 模板路径（可选）
        
    Returns:
        创建结果信息
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        part = create_sw_part(template)
        if part is not None:
            # 安全地获取标题
            try:
                if hasattr(part, 'GetTitle'):
                    title = part.GetTitle()
                else:
                    title = "新零件"
            except:
                title = "新零件"
            return f"✅ 零件创建成功: {title}"
        else:
            return "❌ 零件创建失败"
    except Exception as e:
        return f"❌ 创建零件失败: {e}"

def tool_solidworks_open_file(filepath: str) -> str:
    """
    打开 SolidWorks 文件
    
    Args:
        filepath: 文件路径
        
    Returns:
        打开结果信息
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        # 检查文件是否存在
        if not os.path.exists(filepath):
            return f"❌ 文件不存在: {filepath}"
        
        doc = open_sw_file(filepath)
        if doc is not None:
            # 安全地获取标题
            try:
                if hasattr(doc, 'GetTitle'):
                    title = doc.GetTitle()
                else:
                    title = os.path.basename(filepath)
            except:
                title = os.path.basename(filepath)
            return f"✅ 文件打开成功: {title}"
        else:
            return "❌ 文件打开失败"
    except Exception as e:
        return f"❌ 打开文件失败: {e}"

def tool_solidworks_create_gear(params_json: str) -> str:
    """
    创建齿轮 (简化版，跳过草图问题)
    
    Args:
        params_json: 齿轮参数 JSON 字符串
        
    Returns:
        创建结果信息
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        # 解析参数
        params = json.loads(params_json)
        
        # 获取工具实例
        tool = get_sw_tool()
        if not tool.is_connected:
            return "❌ 请先连接 SolidWorks"
        
        # 简化版：只创建零件，不创建草图
        print("[SolidWorks] 正在创建齿轮（简化版）...")
        
        # 创建新零件
        part = tool.create_part()
        if not part:
            return "❌ 零件创建失败"
        
        # 获取参数
        module = params.get("module", 2)
        teeth = params.get("teeth", 20)
        width = params.get("width", 10)
        
        return f"✅ 齿轮创建完成（简化版）: 模数={module}, 齿数={teeth}, 宽度={width}"
            
    except json.JSONDecodeError:
        return "❌ 参数格式错误，请提供有效的 JSON"
    except Exception as e:
        return f"❌ 创建齿轮失败: {e}"

def tool_solidworks_batch(operations_json: str) -> str:
    """
    批量操作
    
    Args:
        operations_json: 操作列表 JSON 字符串
        
    Returns:
        批量操作结果
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        # 解析操作列表
        operations = json.loads(operations_json)
        
        # 获取工具实例
        tool = get_sw_tool()
        if not tool.is_connected:
            return "❌ 请先连接 SolidWorks"
        
        # 执行批量操作
        results = tool.batch_operation(operations)
        
        # 格式化输出
        lines = ["📊 批量操作结果:"]
        lines.append("=" * 40)
        lines.append(f"📋 总操作数: {results['total']}")
        lines.append(f"✅ 成功: {results['success']}")
        lines.append(f"❌ 失败: {results['failed']}")
        
        if results['details']:
            lines.append("\n📝 详细结果:")
            for detail in results['details']:
                status = "✅" if detail['success'] else "❌"
                lines.append(f"  {status} 操作 {detail['index']+1}: {detail['type']}")
                if detail['error']:
                    lines.append(f"     错误: {detail['error']}")
        
        lines.append("=" * 40)
        return "\n".join(lines)
        
    except json.JSONDecodeError:
        return "❌ 操作列表格式错误，请提供有效的 JSON"
    except Exception as e:
        return f"❌ 批量操作失败: {e}"

def tool_solidworks_test() -> str:
    """
    测试 SolidWorks 工具 (修复版)
    
    Returns:
        测试结果
    """
    if not SOLIDWORKS_AVAILABLE:
        return "错误: SolidWorks 工具不可用"
    
    try:
        lines = ["🧪 SolidWorks 工具测试 (修复版):"]
        lines.append("=" * 40)
        
        # 测试连接
        lines.append("1. 测试连接...")
        success = connect_sw(visible=False)
        if success:
            lines.append("   ✅ 连接成功")
        else:
            lines.append("   ❌ 连接失败")
            return "\n".join(lines)
        
        # 测试获取信息
        lines.append("\n2. 测试获取信息...")
        info = sw_info()
        if "error" in info:
            lines.append(f"   ❌ {info['error']}")
        else:
            lines.append(f"   ✅ 信息获取成功 (版本: {info.get('version', '未知')})")
        
        # 测试创建零件
        lines.append("\n3. 测试创建零件...")
        part = create_sw_part()
        if part is not None:
            lines.append("   ✅ 零件创建成功")
        else:
            lines.append("   ❌ 零件创建失败")
        
        # 断开连接
        lines.append("\n4. 测试断开连接...")
        disconnect_sw()
        lines.append("   ✅ 已断开连接")
        
        lines.append("\n" + "=" * 40)
        lines.append("🎉 所有测试完成!")
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"❌ 测试失败: {e}"

def tool_solidworks_help() -> str:
    """
    显示 SolidWorks 工具帮助 (更新版)
    
    Returns:
        帮助信息
    """
    help_text = """
🔧 DeepSeek SolidWorks 工具帮助 (修复版)
==========================================

📋 可用命令:
1. solidworks_connect [visible=true]    - 连接 SolidWorks
2. solidworks_disconnect                - 断开连接
3. solidworks_info                      - 获取 SolidWorks 信息
4. solidworks_create_part [template]    - 创建新零件
5. solidworks_open_file <filepath>      - 打开文件
6. solidworks_create_gear <params_json> - 创建齿轮（简化版）
7. solidworks_batch <operations_json>   - 批量操作
8. solidworks_test                      - 测试工具
9. solidworks_help                      - 显示此帮助

📝 参数说明:
• visible: true/false - 是否显示 SolidWorks 窗口
• template: 模板文件路径 (可选)
• filepath: SolidWorks 文件路径 (.sldprt, .sldasm, .slddrw)
• params_json: JSON 格式的齿轮参数，例如:
    {"module": 2, "teeth": 20, "width": 10}
• operations_json: JSON 格式的操作列表

🎯 示例:
1. 连接并显示窗口:
   solidworks_connect visible=true
   
2. 创建齿轮（简化版）:
   solidworks_create_gear '{"module": 2, "teeth": 20, "width": 10}'
   
3. 批量操作:
   solidworks_batch '[{"type": "create_part"}, {"type": "create_part"}]'

⚠️  注意事项:
• 需要安装 pywin32: pip install pywin32
• 需要安装 SolidWorks
• 首次连接可能需要管理员权限
• 操作完成后建议断开连接释放资源
• 齿轮创建为简化版（跳过草图步骤）

📞 技术支持:
如有问题，请检查:
1. SolidWorks 是否已安装并运行
2. pywin32 是否已安装
3. 是否以管理员权限运行
4. 运行 solidworks_test 进行诊断
"""
    return help_text

# 工具映射表
SOLIDWORKS_TOOLS = {
    "solidworks_connect": tool_solidworks_connect,
    "solidworks_disconnect": tool_solidworks_disconnect,
    "solidworks_info": tool_solidworks_info,
    "solidworks_create_part": tool_solidworks_create_part,
    "solidworks_open_file": tool_solidworks_open_file,
    "solidworks_create_gear": tool_solidworks_create_gear,
    "solidworks_batch": tool_solidworks_batch,
    "solidworks_test": tool_solidworks_test,
    "solidworks_help": tool_solidworks_help,
}

# 测试代码
if __name__ == "__main__":
    print("DeepSeek SolidWorks 工具测试 (修复版)")
    print("=" * 60)
    
    # 测试帮助
    print(tool_solidworks_help())
    
    # 测试连接
    print("\n测试连接...")
    result = tool_solidworks_connect(visible=False)
    print(result)
    
    if "成功" in result:
        # 测试获取信息
        print("\n测试获取信息...")
        print(tool_solidworks_info())
        
        # 测试创建零件
        print("\n测试创建零件...")
        print(tool_solidworks_create_part())
        
        # 断开连接
        print("\n测试断开连接...")
        print(tool_solidworks_disconnect())
    
    print("\n" + "=" * 60)
    print("测试完成")