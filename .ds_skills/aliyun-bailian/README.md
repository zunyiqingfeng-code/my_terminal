# 阿里百炼（Bailian）技能模块

为DS系统提供阿里云大模型服务集成。

## 功能特性

- ✅ 与阿里百炼模型对话
- ✅ 列出可用模型
- ✅ 健康状态检查
- ✅ 流式响应（如果SDK支持）
- ✅ 自动配置检测（文件/环境变量）
- ✅ 错误处理和重试机制
- ✅ DS系统无缝集成

## 快速开始

### 1. 安装依赖
```bash
# 安装阿里百炼SDK
pip install alibabacloud_bailian20231229 aliyun-python-sdk-core
```

### 2. 配置AccessKey

**方法A：配置文件**（推荐）
创建 `~/.aliyun/config.json`：
```json
{
  "current": "default",
  "profiles": [
    {
      "name": "default",
      "mode": "AK",
      "access_key_id": "你的AccessKey ID",
      "access_key_secret": "你的AccessKey Secret",
      "region_id": "cn-hangzhou",
      "endpoint": "bailian.cn-hangzhou.aliyuncs.com"
    }
  ]
}
```

**方法B：环境变量**
```bash
# Windows
set ALIBABA_CLOUD_ACCESS_KEY_ID=你的AccessKey ID
set ALIBABA_CLOUD_ACCESS_KEY_SECRET=你的AccessKey Secret

# Linux/Mac
export ALIBABA_CLOUD_ACCESS_KEY_ID=你的AccessKey ID
export ALIBABA_CLOUD_ACCESS_KEY_SECRET=你的AccessKey Secret
```

### 3. 获取AccessKey
1. 登录[阿里云控制台](https://aliyun.com)
2. 鼠标悬停右上角头像 → AccessKey管理
3. 创建新的AccessKey（注意保存，只显示一次）

### 4. 开通百炼服务
1. 在阿里云控制台搜索"百炼"
2. 进入产品页面
3. 开通服务（通常有免费额度）

## 使用方法

### 在DS系统中使用

DS会自动检测技能并集成。你可以：

1. **直接对话**：
   ```
   用户：用百炼回答：什么是机器学习？
   DS：调用百炼模型... [回复内容]
   ```

2. **检查状态**：
   ```
   用户：检查百炼状态
   DS：百炼服务状态：健康，可用模型：5个
   ```

3. **指定模型**：
   ```
   用户：用qwen-plus模型回答：写一首诗
   ```

### Python代码中使用

```python
from .ds_skills.aliyun-bailian.skill_bailian import (
    skill_bailian_chat,
    skill_bailian_list_models,
    skill_bailian_health_check
)

# 对话
response = skill_bailian_chat(
    prompt="请介绍阿里百炼",
    model_id="qwen-plus",
    max_tokens=500,
    temperature=0.7
)
print(response)

# 列出模型
models = skill_bailian_list_models()
for model in models[:5]:
    print(f"{model['model_id']}: {model['model_name']}")

# 健康检查
health = skill_bailian_health_check()
print(f"状态: {health['status']}")
```

### 使用BailianSkill类

```python
from .ds_skills.aliyun-bailian.skill_bailian import BailianSkill, BailianConfig

# 自定义配置
config = BailianConfig(
    access_key_id="your-key",
    access_key_secret="your-secret",
    default_model="qwen-max",
    timeout=60
)

# 创建客户端
client = BailianSkill(config)

# 使用
response = client.chat("你好")
print(response)

# 流式响应（如果支持）
for chunk in client.stream_chat("写一个故事"):
    print(chunk, end="", flush=True)
```

## 配置选项

### BailianConfig 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `access_key_id` | str | 必填 | AccessKey ID |
| `access_key_secret` | str | 必填 | AccessKey Secret |
| `endpoint` | str | `bailian.cn-hangzhou.aliyuncs.com` | API端点 |
| `default_model` | str | `qwen-plus` | 默认模型ID |
| `timeout` | int | 30 | 超时时间（秒） |

### skill_bailian_chat 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | str | 必填 | 输入提示 |
| `model_id` | str | `config.default_model` | 模型ID |
| `max_tokens` | int | 1000 | 最大生成token数 |
| `temperature` | float | 0.7 | 温度参数（0-1） |
| `top_p` | float | 0.8 | 核采样参数 |
| `frequency_penalty` | float | 0.0 | 频率惩罚 |
| `presence_penalty` | float | 0.0 | 存在惩罚 |

## 支持的模型

阿里百炼支持多种模型，常见的有：

- `qwen-plus`: 通义千问Plus
- `qwen-max`: 通义千问Max
- `qwen-turbo`: 通义千问Turbo
- `llama2-7b`: Llama2 7B
- `chatglm3-6b`: ChatGLM3 6B

运行 `skill_bailian_list_models()` 查看所有可用模型。

## 错误处理

技能模块包含完善的错误处理：

1. **配置错误**：提示用户检查AccessKey配置
2. **网络错误**：自动重试（最多3次）
3. **API错误**：返回详细的错误信息
4. **配额不足**：提示用户检查账户余额

常见错误及解决方案：

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `InvalidAccessKeyId` | AccessKey ID无效 | 检查AccessKey是否正确 |
| `SignatureDoesNotMatch` | 签名不匹配 | 检查AccessKey Secret |
| `ServiceUnavailable` | 服务不可用 | 检查百炼服务是否开通 |
| `QuotaExceeded` | 配额用完 | 检查账户余额或购买套餐 |

## 性能优化

1. **连接池**：SDK自动管理连接
2. **模型缓存**：模型列表缓存5分钟
3. **超时控制**：可配置请求超时
4. **重试机制**：网络错误自动重试

## 监控和日志

技能模块记录以下信息：

- 请求次数和成功率
- 响应时间分布
- Token使用量
- 错误类型和频率

日志文件：`~/.ds_skills/aliyun-bailian/logs/bailian.log`

## 开发指南

### 添加新功能

1. 在 `skill_bailian.py` 中添加新方法
2. 更新 `skill_config.yaml` 中的功能列表
3. 添加测试用例
4. 更新文档

### 测试

```bash
# 运行单元测试
python -m pytest tests/test_bailian.py

# 运行集成测试
python test_integration.py
```

### 调试

设置环境变量启用调试模式：
```bash
export BAILIAN_DEBUG=1
```

## 常见问题

### Q: 如何知道我的AccessKey是否正确？
A: 运行健康检查：`skill_bailian_health_check()`，如果返回"healthy"则表示配置正确。

### Q: 为什么调用返回"服务未开通"？
A: 需要登录阿里云控制台，搜索"百炼"并开通服务。

### Q: 有免费额度吗？
A: 阿里百炼通常提供一定的免费额度，具体请查看官方定价页面。

### Q: 如何查看使用量和费用？
A: 登录阿里云控制台 → 费用中心 → 使用量查询。

### Q: 支持哪些编程语言？
A: 本技能模块使用Python，阿里云官方还提供Java、Go、Node.js等SDK。

## 更新日志

### v1.0.0 (2026-04-02)
- 初始版本发布
- 支持基本对话功能
- 支持模型列表查询
- 支持健康检查
- DS系统集成

## 相关链接

- [阿里百炼官方文档](https://help.aliyun.com/zh/bailian/)
- [阿里云控制台](https://aliyun.com)
- [Python SDK GitHub](https://github.com/aliyun/alibabacloud-bailian-sdk)
- [DS技能系统文档](../README.md)

## 许可证

本项目基于MIT许可证开源。

## 支持

如有问题，请：
1. 查看本文档的"常见问题"部分
2. 检查日志文件中的错误信息
3. 提交Issue到项目仓库
4. 联系阿里云技术支持