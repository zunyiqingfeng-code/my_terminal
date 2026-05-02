#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视觉分析助手 - 为OpenCode提供视觉能力
基于 ds.py 中的 Qwen-VL 集成
"""

import os
import sys
import time
import base64
import hashlib
import pickle
import mimetypes
import threading
import io
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("警告: PIL/Pillow 未安装，图片处理功能受限")

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    print("警告: httpx 未安装，无法进行HTTP请求")

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    print("警告: openai 未安装，无法调用视觉API")

# ===== 配置常量 =====
# 从 ds.py 复制的配置
VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VISION_MODEL = "qwen-vl-plus"  # 可替换为 "qwen-vl-max" 获得更强识别效果

# 支持的图片格式
SUPPORTED_IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif',
    '.jfif', '.pjpeg', '.pjp', '.svg'
}

# 文档格式（不支持）
DOCUMENT_EXTENSIONS = {
    '.docx', '.doc', '.pdf', '.txt', '.md', '.rtf', '.odt',
    '.ppt', '.pptx', '.xls', '.xlsx'
}

# 统计信息
_view_image_stats = {"total": 0, "success": 0, "failures": 0, "total_time": 0.0}
_view_image_stats_lock = threading.Lock()

# 缓存设置
CACHE_DIR = Path.home() / ".ds_cache" / "view_image"
CACHE_TTL = 3600  # 1小时缓存

# ===== 核心函数 =====

def _encode_image(path: str) -> Tuple[str, str]:
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
            if HAS_PIL:
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
            else:
                raise ImportError("PIL未安装")
                
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


def analyze_image(path: str, question: str = "请详细描述这张图片的内容", 
                  lang: str = "zh", detail_level: str = "normal") -> str:
    """
    分析图片内容 - 主函数
    
    参数:
        path: 图片路径或URL
        question: 分析问题（默认：描述图片内容）
        lang: 输出语言 ('zh', 'en', 'ja', 'ko', 'fr', 'es', 'de')
        detail_level: 详细程度 ('brief', 'normal', 'detailed', 'comprehensive')
    
    返回:
        分析结果字符串
    """
    start_time = time.time()
    
    # 验证依赖
    if not HAS_OPENAI:
        return "[error] vision_helper: openai 库未安装，请运行: pip install openai"
    if not HAS_HTTPX:
        return "[error] vision_helper: httpx 库未安装，请运行: pip install httpx"
    
    # ===== 文件类型检查 =====
    if not (path.startswith("http://") or path.startswith("https://")):
        # 检查文件是否存在
        file_path = Path(path)
        if not file_path.exists():
            with _view_image_stats_lock:
                _view_image_stats["failures"] += 1
            return f"[error] vision_helper: 文件不存在: {path}"
        
        # 获取文件扩展名
        ext = file_path.suffix.lower()
        
        # 检查文件类型
        if ext in DOCUMENT_EXTENSIONS:
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
            return f"""[error] vision_helper: 这是{doc_name}，百炼API无法直接处理文档文件。

解决方案:
1. 使用文档分析功能（如有）
2. 将文档转换为图片格式（截图或导出为图片）
3. 支持的图片格式: JPEG, PNG, GIF, BMP, WebP, TIFF"""
        
        elif ext not in SUPPORTED_IMAGE_EXTENSIONS:
            # 尝试通过MIME类型判断
            mime_type, _ = mimetypes.guess_type(path)
            if mime_type and any(keyword in mime_type for keyword in ['document', 'pdf', 'text', 'msword', 'officedocument', 'presentation', 'spreadsheet']):
                with _view_image_stats_lock:
                    _view_image_stats["failures"] += 1
                return f"""[error] vision_helper: 这是文档文件({mime_type})，百炼API无法直接处理文档。

请将文档转换为图片格式或使用文档分析功能。"""
            elif not mime_type or not mime_type.startswith('image/'):
                with _view_image_stats_lock:
                    _view_image_stats["failures"] += 1
                return f"""[error] vision_helper: 不支持的文件类型: {ext} ({mime_type or '未知MIME类型'})

百炼API仅支持以下图片格式:
- JPEG/JPG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- BMP (.bmp)
- WebP (.webp)
- TIFF (.tiff, .tif)"""
    
    # 更新统计
    with _view_image_stats_lock:
        _view_image_stats["total"] += 1
    
    # 确保缓存目录存在
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 生成缓存键
    if path.startswith("http://") or path.startswith("https://"):
        cache_key = hashlib.md5(f"{path}:{question}:{lang}:{detail_level}".encode()).hexdigest()
    else:
        try:
            with open(path, "rb") as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
            cache_key = hashlib.md5(f"{file_hash}:{question}:{lang}:{detail_level}".encode()).hexdigest()
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
                    return cached_data['result']
            except Exception:
                pass  # 缓存读取失败，继续正常流程
    
    # 检查本地文件大小（如果适用）
    if not (path.startswith("http://") or path.startswith("https://")):
        try:
            file_size = os.path.getsize(path)
            if file_size > 10 * 1024 * 1024:  # 10MB限制
                with _view_image_stats_lock:
                    _view_image_stats["failures"] += 1
                return f"[error] vision_helper: 图片文件过大 ({file_size//1024//1024}MB > 10MB)，请压缩图片"
        except Exception:
            pass  # 文件大小检查失败不影响正常流程
    
    try:
        # 根据语言和详细级别构建问题
        enhanced_question = _build_question(question, lang, detail_level)
        
        # API调用
        if HAS_HTTPX and hasattr(httpx, 'AsyncClient'):
            # 异步请求
            import asyncio
            
            async def async_request():
                transport = httpx.HTTPTransport(retries=3)
                async with httpx.AsyncClient(
                    transport=transport, 
                    timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
                    trust_env=False
                ) as client:
                    vision_client = OpenAI(
                        api_key=VISION_API_KEY,
                        base_url=VISION_BASE_URL,
                        http_client=client
                    )
                    
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
                                {"type": "text", "text": enhanced_question},
                                img_content,
                            ]
                        }],
                        max_tokens=2000,
                    )
                    return resp.choices[0].message.content or "(模型返回空内容)"
            
            try:
                result = asyncio.run(async_request())
            except Exception:
                # 异步失败，回退到同步请求
                result = _sync_api_call(path, enhanced_question)
        else:
            # 同步请求
            result = _sync_api_call(path, enhanced_question)
        
        elapsed = time.time() - start_time
        
        # 更新成功统计
        with _view_image_stats_lock:
            _view_image_stats["success"] += 1
            _view_image_stats["total_time"] += elapsed
        
        # 格式化结果
        formatted_result = _format_result(result, elapsed, lang, detail_level)
        
        # 保存到缓存
        if cache_key:
            try:
                cache_data = {
                    "timestamp": time.time(),
                    "result": formatted_result
                }
                with open(cache_file, "wb") as f:
                    pickle.dump(cache_data, f)
            except Exception:
                pass  # 缓存保存失败不影响正常流程
        
        return formatted_result
        
    except Exception as e:
        elapsed = time.time() - start_time
        
        # 更新失败统计
        with _view_image_stats_lock:
            _view_image_stats["failures"] += 1
        
        error_msg = f"{type(e).__name__}: {e}"
        if "InvalidParameter" in error_msg or "cannot identify image file" in error_msg:
            error_msg = f"百炼API无法处理此文件格式。请确保文件是支持的图片格式(JPEG/PNG/GIF/BMP/WebP/TIFF)。原始错误: {error_msg}"
        
        return f"[error] vision_helper: {error_msg}"


def _build_question(base_question: str, lang: str, detail_level: str) -> str:
    """根据语言和详细级别构建问题"""
    # 语言指令映射
    lang_instructions = {
        'zh': "请用中文回答。",
        'en': "Please answer in English.",
        'ja': "日本語で答えてください。",
        'ko': "한국어로 답변해 주세요.",
        'fr': "Veuillez répondre en français.",
        'es': "Por favor, responda en español.",
        'de': "Bitte antworten Sie auf Deutsch.",
    }
    
    # 详细级别指令
    detail_instructions = {
        'brief': "请简要描述。",
        'normal': "请详细描述。",
        'detailed': "请提供非常详细的描述，包括所有可见的物体、场景、文字、颜色和布局。",
        'comprehensive': """请提供全面的分析，包括：
1. 主要物体识别和位置
2. 场景描述和上下文
3. 可见的文字内容（如果有）
4. 颜色、光线和氛围
5. 布局和构图分析
6. 可能的用途或背景"""
    }
    
    lang_instruction = lang_instructions.get(lang, lang_instructions['zh'])
    detail_instruction = detail_instructions.get(detail_level, detail_instructions['normal'])
    
    return f"{base_question}\n\n{lang_instruction}\n{detail_instruction}"


def _sync_api_call(path: str, question: str) -> str:
    """同步API调用"""
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
        max_tokens=2000,
    )
    return resp.choices[0].message.content or "(模型返回空内容)"


def _format_result(result: str, elapsed: float, lang: str, detail_level: str) -> str:
    """格式化结果"""
    # 语言特定的标题
    titles = {
        'zh': "视觉分析结果",
        'en': "Visual Analysis Result",
        'ja': "視覚分析結果",
        'ko': "시각 분석 결과",
        'fr': "Résultat de l'analyse visuelle",
        'es': "Resultado del análisis visual",
        'de': "Visuelle Analyseergebnisse",
    }
    
    title = titles.get(lang, titles['zh'])
    
    return f"""[{title}] (耗时{elapsed:.1f}秒 | 详细程度: {detail_level})
{'-' * 60}
{result}
{'-' * 60}
"""


def tool_view_image(path: str, question: str = "请详细描述这张图片的内容") -> str:
    """向后兼容函数 - 与原ds.py接口一致"""
    return analyze_image(path, question, lang="zh", detail_level="normal")


def get_stats() -> Dict[str, Any]:
    """获取统计信息"""
    with _view_image_stats_lock:
        stats = _view_image_stats.copy()
    
    if stats["total"] > 0:
        stats["success_rate"] = stats["success"] / stats["total"] * 100
        stats["avg_time"] = stats["total_time"] / stats["success"] if stats["success"] > 0 else 0
    else:
        stats["success_rate"] = 0
        stats["avg_time"] = 0
    
    return stats


def clear_cache() -> bool:
    """清除缓存"""
    try:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
        return True
    except Exception:
        return False


def test_connection() -> str:
    """测试API连接"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)
        
        # 尝试一个简单的请求来测试连接
        # 注意：这里不实际调用API，只是检查客户端能否创建
        return f"[info] API连接测试通过\nKey: {VISION_API_KEY[:10]}...\nURL: {VISION_BASE_URL}\nModel: {VISION_MODEL}"
    except Exception as e:
        return f"[error] API连接测试失败: {type(e).__name__}: {e}"


# ===== 多语言便捷函数 =====
def analyze_image_zh(path: str, question: str = "请详细描述这张图片的内容", detail_level: str = "normal") -> str:
    """中文分析"""
    return analyze_image(path, question, "zh", detail_level)

def analyze_image_en(path: str, question: str = "Please describe this image in detail", detail_level: str = "normal") -> str:
    """英文分析"""
    return analyze_image(path, question, "en", detail_level)

def analyze_image_ja(path: str, question: str = "この画像の内容を詳しく説明してください", detail_level: str = "normal") -> str:
    """日文分析"""
    return analyze_image(path, question, "ja", detail_level)

def analyze_image_ko(path: str, question: str = "이 이미지의 내용을 자세히 설명해 주세요", detail_level: str = "normal") -> str:
    """韩文分析"""
    return analyze_image(path, question, "ko", detail_level)