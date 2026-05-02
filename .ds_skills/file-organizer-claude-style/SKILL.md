---
name: file-organizer-claude-style
description: 按文件类型自动整理目录，创建分类文件夹并移动文件
allowed-tools: [shell, list_dir, glob_files, write_file, read_file]
context: fork
effort: medium
paths: "**/*.{doc,docx,md,bat,py,js,html,css,jpg,png,pdf,txt}"
---

# 文件整理技能 (Claude风格)

## 任务
扫描指定目录，按文件类型自动分类整理到相应的文件夹中。

## 输入参数
- `target_dir`: 要整理的目录路径（默认：当前目录）
- `rules`: 自定义分类规则（可选）
- `dry_run`: 试运行模式，不实际移动文件（默认：false）

## 输出结果
- 整理后的目录结构
- 移动文件的数量统计
- 创建的分类文件夹列表
- 详细的操作日志

## 默认分类规则

```yaml
文档类:
  - 扩展名: [.doc, .docx, .pdf, .md, .txt]
  - 文件夹: "文档"
  
代码类:
  - 扩展名: [.py, .js, .java, .cpp, .c, .h, .html, .css]
  - 文件夹: "代码"
  
图片类:
  - 扩展名: [.jpg, .jpeg, .png, .gif, .bmp, .svg]
  - 文件夹: "图片"
  
数据类:
  - 扩展名: [.csv, .json, .xml, .xlsx, .xls]
  - 文件夹: "数据"
  
脚本类:
  - 扩展名: [.bat, .sh, .ps1, .cmd]
  - 文件夹: "脚本"
  
其他类:
  - 扩展名: [其他所有类型]
  - 文件夹: "其他"
```

## 执行步骤

### 步骤1：验证和准备
1. 检查目标目录是否存在
2. 解析用户提供的分类规则（或使用默认规则）
3. 创建操作日志记录器

### 步骤2：扫描目录
1. 使用`list_dir`工具列出目录内容
2. 过滤出文件（排除目录）
3. 按扩展名统计文件分布

### 步骤3：创建分类文件夹
1. 根据分类规则创建对应的文件夹
2. 如果文件夹已存在，跳过创建
3. 记录创建的文件夹

### 步骤4：移动文件
1. 遍历所有文件
2. 根据扩展名确定目标文件夹
3. 移动文件到对应文件夹
   - 如果目标文件已存在，添加数字后缀
   - 记录每个移动操作

### 步骤5：生成报告
1. 统计整理结果
2. 生成详细的整理报告
3. 提供后续建议

## 错误处理
- 如果目标目录不存在：返回错误信息
- 如果权限不足：提示用户并跳过相关文件
- 如果移动失败：记录错误并继续处理其他文件
- 如果磁盘空间不足：停止操作并提示

## 示例调用

### 方式1：直接调用
```python
# 在DS系统中调用
result = invoke_skill("file-organizer-claude-style", {
    "target_dir": "~/Desktop",
    "dry_run": false
})
```

### 方式2：通过代理调用
```yaml
# 代理配置中预加载此技能
skills:
  - file-organizer-claude-style
```

### 方式3：通过命令调用
```
/clean-desktop --target ~/Desktop --quick
```

## 返回格式

```json
{
  "success": true,
  "stats": {
    "total_files": 42,
    "files_moved": 38,
    "folders_created": 5,
    "errors": 0
  },
  "folders": ["文档", "代码", "图片", "数据", "脚本"],
  "operations": [
    {"file": "report.doc", "from": ".", "to": "文档/", "status": "moved"},
    {"file": "script.py", "from": ".", "to": "代码/", "status": "moved"}
  ],
  "report": "整理了38个文件，创建了5个分类文件夹。"
}
```

## 最佳实践建议
1. **定期整理**: 建议每周整理一次桌面
2. **备份重要文件**: 整理前备份重要文件
3. **自定义规则**: 根据工作习惯调整分类规则
4. **试运行**: 首次使用时先使用dry_run模式测试