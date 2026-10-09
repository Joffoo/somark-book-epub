# SoMark Book to EPUB (somark-book-epub)

> 基于篇目语义切片与 SoMark API 的出版级长篇图书数字化与 EPUB 3 排版引擎。  
> Semantic chapter-aware book digitization pipeline converting long PDFs into publishing-grade EPUB 3 and Obsidian notes with SoMark OCR.

<p align="center">
  <a href="#简体中文">简体中文</a> •
  <a href="#english">English</a> •
  <a href="#license">License</a>
</p>

---

<a name="简体中文"></a>
## 简体中文

`somark-book-epub` 是一款面向整本长篇图书（单作者专著、文集、小说、学术论著、翻译文学）的现代化图书数字化与电子书重构工具。

它融合了**“篇目语义感知切片 + SoMark 批量高保真 OCR + 远程配图本地化 + 智能体自主排版审校 + Pandoc EPUB 3 编译”**的闭环流水线，彻底克服了传统按固定页数机械硬切带来的跨页断句、接缝断裂与标题混乱难题，实现“物理切片边界 = 语义章节边界”。

### 🌟 核心优势

1. **语义篇目切片（Semantic Chapter Slicing）**
   - 自动探测 PDF 原生书签大纲或扫描版目录页，按完整文章/大章物理切分；
   - 物理边界即语义边界，天然消除跨切片未闭合对白、跨页断句与小节孤立问题。
2. **极速高保真 SoMark 批量解析**
   - 15 页通常仅需约 13 秒，高保真还原段落排版、表格与高清配图；
   - 严格遵循 4 QPS 速率限制，内置断点续跑与额度保护，已识别切片自动跳过，杜绝额度浪费。
3. **配图离线化与本地路径重写**
   - 异步并发拉取临时 OSS 配图至本地 `images/` 目录，彻底消除外部网络依赖，打造真正离线可读的出版物。
4. **Agent 认知智能审校 (Map-Reduce)**
   - 脚本做确定性搬运，排版语义全归 Agent 自主裁决：依托大纲确立大标题 `##`，归一化篇内小节与独立序号为 `###`；
   - 语义绑定每张配图下方的原书图题（`![图题](...)`），自动剥离 CIP、条形码、定价等物理印刷工业残留。
5. **经典书卷感与 EPUB 3 双向弹框气泡**
   - 内置出版级样式表（`assets/styles_book.css`），支持楷体署名（`<p class="chapter-author">`）、居中题记（`<div class="epigraph">`）与通用块引用；
   - 自动注入 EPUB 3 双向弹出式气泡脚注（`epub:type="noteref"` / `<aside epub:type="footnote">`）；
   - 原生支持 W3C 标准 MathML 数学公式。

---

### 🏗 全流程处理架构

```
[原始图书 PDF]
       │
       ▼ (Gate 1: 篇目感知切片与书型研判)
 semantic_slicer.py ──> 提取原生书签或目录页，按真实篇目切为 parts/*.pdf
       │                提取高清封面 cover.png，研判全书体例 Profile
       ▼ (Gate 2: SoMark 批量高保真识别 - Map)
 somark_batch.py ─────> 4 QPS 限制并发调度，断点续跑防浪费，落盘 raw_md/*.md
       │
       ▼ (Gate 3: 远程配图本地化下载 - Map)
 localize_images.py ──> 异步下载 OSS 配图至 images/，重写 Markdown 相对路径
       │
       ▼ (Gate 4: 出版级排版精修 - Map)
 Agent / Subagents ───> 注入 references/editorial_guidelines.md 规约与动态书型：
       │                篇名对齐 ##、序号提级 ###、图题语义绑定、物理去噪
       ▼ (Gate 5: 出厂汇编与编译成书 - Reduce)
 chapter_assembler.py ─> 隔离各章脚注命名空间 [^c01_1]，生成全书主笔记 《书名》.md
 epub_builder.py ──────> Pandoc 注入 styles_book.css 编译 EPUB 3，注入双向弹框气泡注释
       │
       ▼ (出厂自检门禁)
 主 Agent 校验 ───────> TOC 目录大纲完整性核验、图文去重与首尾版面抽验
```

---

### 📦 运行环境与安装

#### 1. 系统依赖
- **Python**: 3.10 及以上
- **Pandoc**: 3.0 及以上 ([Pandoc 安装指引](https://pandoc.org/installing.html))

#### 2. 安装步骤
```bash
# 克隆代码仓库
git clone https://github.com/Joffoo/somark-book-epub.git
cd somark-book-epub

# 安装 Python 依赖
pip install -r requirements.txt

# 环境诊断体检 (Doctor Mode)
python scripts/digitize_book.py --doctor
```

---

### 🔑 API Key 安全配置指南

本工具严格遵循凭证安全隔离原则，**绝不硬编码任何密钥，控制台与日志中绝不打印任何密钥片段**。

请通过以下方式配置您的 SoMark API Key（可访问 [SoMark 官网](https://somark.cn) 获取）：

#### 方式 A：系统环境变量（推荐）
- **Windows PowerShell**:
  ```powershell
  $env:SOMARK_API_KEY = "sk-xxxxxxxx"
  ```
- **macOS / Linux**:
  ```bash
  export SOMARK_API_KEY="sk-xxxxxxxx"
  ```

#### 方式 B：本地 `.env` 文件（已加入 `.gitignore`，绝不上传 GitHub）
复制样例模板并填入您的 Key：
```bash
cp .env.example .env
# 编辑 .env 文件填入 SOMARK_API_KEY=sk-xxxxxxxx
```

---

### 🚀 命令行使用指南 (`digitize_book.py`)

主控脚本支持全自动运行与五大阶段独立执行：

```bash
# 1. 环境自检
python scripts/digitize_book.py --doctor

# 2. 一键全自动转换整本书
python scripts/digitize_book.py "path/to/book.pdf"

# 3. 分阶段独立推进
# 阶段 1：仅执行语义切片 (支持传入自定义切片计划 --plan slice_plan.json)
python scripts/digitize_book.py "path/to/book.pdf" --slice-only

# 阶段 2：仅执行 SoMark 批量 OCR (自动跳过已识别切片)
python scripts/digitize_book.py "<工作目录>" --ocr-only

# 阶段 3：仅执行配图本地化下载与相对路径重写
python scripts/digitize_book.py "<工作目录>" --localize-only

# 阶段 4：仅执行篇章汇编与排版规范化
python scripts/digitize_book.py "<工作目录>" --assemble-only

# 阶段 5：仅执行 EPUB 3 编译
python scripts/digitize_book.py "<工作目录>" --epub-only
```

---

### 🤖 配合 AI Coding Agent (SOP & 验收门禁)

在作为 Antigravity / Claude Agent Skill 使用时，主 Agent 严格遵守五阶门禁推进：
- **Gate 1**：`parts/*.pdf` 生成完毕，篇目数量等于计划条目数，确立书型体例；
- **Gate 2**：`raw_md/*.md` 数量 100% 等于切片数，且全部非空；
- **Gate 3**：`images/` 资产落盘，`localized_md/*.md` 中 100% 消除远程 URL；
- **Gate 4**：精修各章节，每章顶部唯一 `##`，篇内小节与独立序号统一为 `###`，图题绑定完成，清除物理条码/CIP 残留；
- **Gate 5**：生成最终 `《书名》.epub` 与 `《书名》.md`，双向弹框注释与 MathML 公式校验通过，执行 TOC 目录完整性出厂核验。

---

<a name="english"></a>
## English

`somark-book-epub` is a modern, publishing-grade book digitization and EPUB 3 restructuring toolkit designed for full-length books, monographs, literature, textbooks, and anthologies.

It implements a unified agentic pipeline: **Semantic Chapter Slicing + High-Speed SoMark OCR + Image Localization + Cognitive Agent Styling + Pandoc EPUB 3 Compilation**. By aligning physical slice boundaries directly with semantic chapters, it completely eliminates sentence splitting across slices, broken dialogue quotes, and fragmented subheadings.

### 🌟 Key Features

1. **Semantic Chapter Slicing**
   - Automatically detects native PDF bookmarks or TOC pages to slice PDFs by article/chapter;
   - Physical boundary equals semantic boundary, resolving cross-slice stitching issues at the architectural root.
2. **High-Speed, High-Fidelity SoMark Batch OCR**
   - 15 pages in ~13 seconds, accurately extracting headings, tables, and illustrations;
   - Adheres strictly to the 4 QPS rate limit, with cache protection that skips already-parsed parts to preserve quota.
3. **Offline Image Localization**
   - Concurrently downloads CDN images into local `images/` and rewrites Markdown paths to relative paths, producing truly offline digital publications.
4. **Cognitive Agent Typography (Map-Reduce)**
   - Deterministic scripts handle plumbing; cognitive agents judge semantics. Agents align H2 chapter titles, normalize subheadings/numeral sections to H3, bind captions to figures, and strip physical boilerplate (CIP/barcodes).
5. **Publishing-Grade Typography & EPUB 3 Popup Footnotes**
   - Inlined classical CSS (`assets/styles_book.css`) supporting KaiTi author signatures (`<p class="chapter-author">`), epigraphs (`<div class="epigraph">`), and blockquotes;
   - Injects EPUB 3 bidirectional popup footnotes (`epub:type="noteref"` / `<aside epub:type="footnote">`);
   - Native W3C MathML formula rendering.

---

### 📦 Prerequisites & Installation

#### Requirements
- **Python**: 3.10+
- **Pandoc**: 3.0+ ([Installation Guide](https://pandoc.org/installing.html))

#### Setup
```bash
git clone https://github.com/Joffoo/somark-book-epub.git
cd somark-book-epub

pip install -r requirements.txt

# Run doctor check
python scripts/digitize_book.py --doctor
```

---

### 🔑 Safe API Key Configuration

The tool enforces strict secret isolation: **no keys are hardcoded, and no key tokens/masks are printed to logs or the console**.

Obtain an API key from [SoMark](https://somark.cn) (Mainland China) or [SoMark AI](https://somark.ai) (Global).

#### Option A: Environment Variables (Recommended)
- **Windows PowerShell**:
  ```powershell
  $env:SOMARK_API_KEY = "sk-xxxxxxxx"
  ```
- **macOS / Linux**:
  ```bash
  export SOMARK_API_KEY="sk-xxxxxxxx"
  ```

#### Option B: Local `.env` (Protected by `.gitignore`)
```bash
cp .env.example .env
# Edit .env to set SOMARK_API_KEY=sk-xxxxxxxx
```

---

### 🚀 CLI Quick Start (`digitize_book.py`)

```bash
# 1. Environment diagnostic check
python scripts/digitize_book.py --doctor

# 2. End-to-end automated conversion
python scripts/digitize_book.py "path/to/book.pdf"

# 3. Step-by-step modular commands
python scripts/digitize_book.py "path/to/book.pdf" --slice-only
python scripts/digitize_book.py "<work_dir>" --ocr-only
python scripts/digitize_book.py "<work_dir>" --localize-only
python scripts/digitize_book.py "<work_dir>" --assemble-only
python scripts/digitize_book.py "<work_dir>" --epub-only
```

---

<a name="license"></a>
## License

This project is licensed under the [MIT License](LICENSE).
