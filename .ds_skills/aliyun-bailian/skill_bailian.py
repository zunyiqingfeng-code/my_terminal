"""
阿里百炼（Bailian）技能模块
为DS系统提供阿里云大模型服务集成
"""

import os
import json
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

try:
    from alibabacloud_bailian20231229.client import Client
    from alibabacloud_bailian20231229 import models as bailian_models
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_tea_util import models as util_models
    BAILIAN_AVAILABLE = True
except ImportError:
    BAILIAN_AVAILABLE = False
    print("警告: 阿里百炼SDK未安装，请运行: pip install alibabacloud_bailian20231229")

@dataclass
class BailianConfig:
    """阿里百炼配置"""
    access_key_id: str
    access_key_secret: str
    endpoint: str = "bailian.cn-hangzhou.aliyuncs.com"
    default_model: str = "qwen-plus"
    timeout: int = 30
    
    @classmethod
    def from_file(cls, config_path: Optional[str] = None):
        """从配置文件加载配置"""
        if config_path is None:
            config_path = os.path.expanduser("~/.aliyun/config.json")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # 获取当前激活的profile
        current_profile = config_data.get('current', 'default')
        profiles = config_data.get('profiles', [])
        
        profile = next((p for p in profiles if p.get('name') == current_profile), None)
        if not profile:
            raise ValueError(f"未找到配置profile: {current_profile}")
        
        return cls(
            access_key_id=profile.get('access_key_id', ''),
            access_key_secret=profile.get('access_key_secret', ''),
            endpoint=profile.get('endpoint', 'bailian.cn-hangzhou.aliyuncs.com')
        )
    
    @classmethod
    def from_env(cls):
        """从环境变量加载配置"""
        access_key_id = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID') or os.environ.get('ALIYUN_ACCESS_KEY_ID')
        access_key_secret = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET') or os.environ.get('ALIYUN_ACCESS_KEY_SECRET')
        
        if not access_key_id or not access_key_secret:
            raise ValueError("环境变量中未找到阿里云AccessKey配置")
        
        return cls(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret
        )

class BailianSkill:
    """阿里百炼技能类"""
    
    def __init__(self, config: Optional[BailianConfig] = None):
        """初始化百炼客户端"""
        if not BAILIAN_AVAILABLE:
            raise ImportError("阿里百炼SDK未安装，请先安装: pip install alibabacloud_bailian20231229")
        
        # 加载配置
        if config is None:
            try:
                config = BailianConfig.from_file()
            except (FileNotFoundError, ValueError):
                try:
                    config = BailianConfig.from_env()
                except ValueError:
                    raise ValueError(
                        "未找到阿里百炼配置。请:\n"
                        "1. 创建 ~/.aliyun/config.json 文件\n"
                        "2. 或设置环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID 和 ALIBABA_CLOUD_ACCESS_KEY_SECRET"
                    )
        
        self.config = config
        
        # 创建OpenAPI配置
        openapi_config = open_api_models.Config(
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
            endpoint=config.endpoint,
            connect_timeout=config.timeout * 1000,  # 毫秒
            read_timeout=config.timeout * 1000
        )
        
        # 初始化客户端
        self.client = Client(openapi_config)
        
        # 缓存模型列表
        self._models_cache = None
    
    def chat(self, 
             prompt: str, 
             model_id: Optional[str] = None,
             max_tokens: int = 1000,
             temperature: float = 0.7,
             **kwargs) -> str:
        """
        与模型对话
        
        Args:
            prompt: 输入提示
            model_id: 模型ID，默认为配置中的default_model
            max_tokens: 最大生成token数
            temperature: 温度参数
            **kwargs: 其他参数
            
        Returns:
            模型回复文本
        """
        if model_id is None:
            model_id = self.config.default_model
        
        request = bailian_models.CreateCompletionRequest(
            model_id=model_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
        
        try:
            response = self.client.create_completion(request)
            
            if response.body and response.body.choices:
                return response.body.choices[0].text
            else:
                return "模型未返回有效响应"
                
        except Exception as e:
            return f"调用失败: {str(e)}"
    
    def list_models(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        列出可用模型
        
        Args:
            refresh: 是否刷新缓存
            
        Returns:
            模型列表
        """
        if self._models_cache is not None and not refresh:
            return self._models_cache
        
        try:
            request = bailian_models.ListModelsRequest()
            response = self.client.list_models(request)
            
            models = []
            if response.body and hasattr(response.body, 'models'):
                for model in response.body.models:
                    models.append({
                        'model_id': getattr(model, 'model_id', ''),
                        'model_name': getattr(model, 'model_name', ''),
                        'description': getattr(model, 'description', ''),
                        'capabilities': getattr(model, 'capabilities', [])
                    })
            
            self._models_cache = models
            return models
            
        except Exception as e:
            print(f"获取模型列表失败: {e}")
            return []
    
    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """
        获取特定模型信息
        
        Args:
            model_id: 模型ID
            
        Returns:
            模型信息字典，如果未找到则返回None
        """
        models = self.list_models()
        for model in models:
            if model['model_id'] == model_id:
                return model
        return None
    
    def stream_chat(self, 
                   prompt: str, 
                   model_id: Optional[str] = None,
                   max_tokens: int = 1000,
                   temperature: float = 0.7):
        """
        流式对话（如果支持）
        
        Args:
            prompt: 输入提示
            model_id: 模型ID
            max_tokens: 最大生成token数
            temperature: 温度参数
            
        Yields:
            生成的文本片段
        """
        # 注意：需要检查SDK是否支持流式响应
        if model_id is None:
            model_id = self.config.default_model
        
        # 这里实现流式响应逻辑
        # 由于SDK可能不支持流式，先返回完整响应
        response = self.chat(prompt, model_id, max_tokens, temperature)
        yield response
    
    def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            包含健康状态和信息的字典
        """
        try:
            models = self.list_models(refresh=True)
            
            return {
                'status': 'healthy' if models else 'degraded',
                'model_count': len(models),
                'available_models': [m['model_id'] for m in models[:3]],
                'default_model': self.config.default_model,
                'config_source': 'file' if os.path.exists(os.path.expanduser("~/.aliyun/config.json")) else 'env'
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'config_source': 'unknown'
            }

# DS技能接口函数
def skill_bailian_chat(prompt: str, **kwargs) -> str:
    """
    DS技能接口：与阿里百炼对话
    
    Args:
        prompt: 输入提示
        **kwargs: 其他参数（model_id, max_tokens, temperature等）
        
    Returns:
        模型回复
    """
    try:
        skill = BailianSkill()
        return skill.chat(prompt, **kwargs)
    except Exception as e:
        return f"技能执行失败: {e}"

def skill_bailian_list_models() -> List[Dict[str, Any]]:
    """
    DS技能接口：列出可用模型
    
    Returns:
        模型列表
    """
    try:
        skill = BailianSkill()
        return skill.list_models()
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []

def skill_bailian_health_check() -> Dict[str, Any]:
    """
    DS技能接口：健康检查
    
    Returns:
        健康状态信息
    """
    try:
        skill = BailianSkill()
        return skill.health_check()
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e)
        }

# 测试函数
def test():
    """测试函数"""
    print("测试阿里百炼技能模块")
    print("=" * 50)
    
    try:
        # 健康检查
        print("1. 健康检查:")
        health = skill_bailian_health_check()
        print(f"   状态: {health.get('status')}")
        print(f"   模型数量: {health.get('model_count', 0)}")
        
        # 列出模型
        print("\n2. 可用模型:")
        models = skill_bailian_list_models()
        for i, model in enumerate(models[:5], 1):  # 显示前5个
            print(f"   {i}. {model.get('model_id')}: {model.get('model_name', '')}")
        
        # 测试对话
        print("\n3. 测试对话:")
        response = skill_bailian_chat("你好，请用一句话介绍阿里百炼")
        print(f"   回复: {response}")
        
        print("\n✓ 测试完成")
        
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        print("\n可能的原因:")
        print("1. 未安装SDK: pip install alibabacloud_bailian20231229")
        print("2. 未配置AccessKey")
        print("3. 百炼服务未开通")
        print("4. 网络问题")

if __name__ == "__main__":
    test()