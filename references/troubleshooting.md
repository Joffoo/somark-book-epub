# 故障排查与运维指南 (Troubleshooting)

本文档列出了 `somark-book-epub` 运行过程中常见问题与解决方案。

---

## 1. SoMark API 相关

### 1.1 错误代码与处置
- `1107`: API Key 无效或未设置。请检查 `$env:SOMARK_API_KEY` 是否正确设置。
- `2000`: 请求参数不合法。
- `QPS 限制 (429)`: 账号限制为 4 QPS。`somark_batch.py` 默认并发度设为 2，严禁在外部多进程并行发起超过 4 个实例。

### 1.2 断点续跑与额度保护
- `somark_batch.py` 内置断点保护机制：如果 `raw_md/*.md` 已经存在且非空，脚本会自动跳过，绝不重复调用 API，防止误消耗额度。
- 若确实需要重新识别某一片，可使用 `--force-ocr` 参数。

---

## 2. 篇目感知与切片 (Semantic Slicing)

### 2.1 PDF 无内置书签大纲
- 很多扫描版 PDF 或自制 PDF 没有目录书签。此时 `semantic_slicer.py` 会导出前 10~15 页至 `preview_toc.pdf`。
- 主 Agent 可通过 `view_file` 或调用 SoMark 解析 `preview_toc.pdf` 得到真实目录页文字。
- 随后快速生成 `slice_plan.json`：
  ```json
  [
    {"part_index": 1, "title": "卷首与目录", "start_page": 1, "end_page": 10},
    {"part_index": 2, "title": "第一章", "start_page": 11, "end_page": 35},
    {"part_index": 3, "title": "第二章", "start_page": 36, "end_page": 60}
  ]
  ```
- 再次运行 `python scripts/digitize_book.py "<PDF>" --plan slice_plan.json` 即可完成精准切片。

---

## 3. 配图本地化与离线化 (Image Localization)

### 3.1 为什么必须本地化？
- SoMark 返回的图片托管在临时阿里云 OSS 图床上，不仅有网络延迟，且链接可能过期。
- `localize_images.py` 会自动扫描所有 Markdown，并发下载至 `images/` 目录并修改为相对路径。

### 3.2 图像 Alt 多行换行匹配
- SoMark 生成的图像视觉描述可能包含多行换行，必须使用支持换行的非贪婪匹配（`[\s\S]*?`），确保所有 OSS 图像链接完整提取并下载。

---

## 4. Pandoc 与 EPUB 3 编译

### 4.1 Pandoc 找不到
- 确认系统已安装 Pandoc（Windows 用户确认已加入 PATH，或安装至默认路径 `C:\Program Files\Pandoc`）。
- 运行 `python scripts/digitize_book.py --doctor` 可快速检测。

### 4.2 Windows 命令行传参乱码
- Windows 控制台下直接通过 CLI 传中文参数容易乱码。`epub_builder.py` 统一通过 UTF-8 编码的 `pandoc_meta.yaml` 传递书名、作者、语言等元数据。

### 4.3 目录切章与层级位移 (`--shift-heading-level-by=-1`)
- Pandoc 默认以一级标题（H1）切分 XHTML 章节与生成目录。
- 篇章切片内的大标题使用二级标题（`##`），因此编译时必须配置 `--shift-heading-level-by=-1`，将 `##` 位移为 `<h1>`，实现多章节切分与完整目录树构建。

### 4.4 数学公式与 MathML
- 编译时默认启用 `--mathml`，数学公式将转为矢量排版，EPUB 阅读器原生支持。
