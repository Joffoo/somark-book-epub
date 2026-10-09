---
name: somark-book-epub
description: Convert PDF books (monographs, anthologies, literature, textbooks) to publication-grade EPUB 3 and Obsidian Markdown via semantic slicing and SoMark batch OCR. Triggers on "SoMark转电子书", "按篇目做EPUB", "扫描书制作EPUB", "图书OCR排版EPUB", "PDF制作EPUB".
---

# SoMark Book to EPUB (语义篇目切片与出版级电子书数字化工具)

将长篇 PDF（单作者专著、文集、小说、学术论著、译作）转换为出版级 EPUB 3 电子书与 Obsidian 典藏笔记。

核心范式：**物理切片边界 = 语义章节边界 (Map-Reduce)**。主 Agent 感知大纲切分篇目并研判书型，SoMark 执行批量高保真 OCR，解耦并行精修版面，Pandoc 编译带气泡弹注的标准 EPUB 3，最后执行总编级自检出厂。

---

## 统一处理架构 (Map-Reduce)

```
[原始图书 PDF]
       │
       ▼ (Gate 1: 篇目感知切片与书型研判)
 semantic_slicer.py ──> 提取书签/目录页切分 parts/*.pdf，提取封面 cover.png
       │                研判全书体例 Profile (单作者 / 文集 / 译作) 与用户定制意图
       ▼ (Gate 2: SoMark 批量高保真识别 - Map)
 somark_batch.py ─────> 4 QPS 并发调度，断点续跑防浪费，落盘 raw_md/*.md
       │
       ▼ (Gate 3: 远程配图本地化下载 - Map)
 localize_images.py ──> 异步下载 OSS 配图至 images/，重写 Markdown 相对路径
       │
       ▼ (Gate 4: 出版级排版精修 - Map)
 Agent / Subagents ───> 注入 references/editorial_guidelines.md 规约与动态书型：
       │                H2 章节标题、独立序号提级 H3、图题方括号绑定、物理去噪
       ▼ (Gate 5: 出厂汇编与编译成书 - Reduce)
 chapter_assembler.py ─> 隔离各章脚注命名空间 [^c01_1]，生成全书主笔记 《书名》.md
 epub_builder.py ──────> Pandoc 注入 styles_book.css 编译 EPUB 3，后处理注入弹框气泡
       │
       ▼ (出厂自检门禁)
 主 Agent 自检 ───────> TOC 目录大纲完整性核验、图文去重与首尾版面抽验
```

---

## 主控流水线寻址与 CLI 速查

- 当前工程上下文：`python .agent/skills/somark-book-epub/scripts/digitize_book.py`
- 独立/全局上下文：`python <Skill根目录>/scripts/digitize_book.py`

| 指令 | 作用 |
| :--- | :--- |
| `digitize_book.py --doctor` | 环境体检（Python 3.10+, PyMuPDF, aiohttp, Pandoc, SOMARK_API_KEY） |
| `digitize_book.py "<PDF>" --slice-only` | 执行篇目感知切片（支持 `--plan slice_plan.json`） |
| `digitize_book.py "<目录>" --ocr-only` | 批量 SoMark OCR（支持 `--concurrency 2`，自动跳过已有片） |
| `digitize_book.py "<目录>" --localize-only` | 异步下载远程图片至 `images/` 并重写相对路径 |
| `digitize_book.py "<目录>" --assemble-only` | 汇编独立章节、隔离脚注命名空间、生成全书主笔记 |
| `digitize_book.py "<目录>" --epub-only` | Pandoc 编译出版级 EPUB 3 |
| `digitize_book.py "<PDF>"` | 一键全流程流水线 |

---

## 执行规约与严格验收门禁 (Agent SOP & Completion Gates)

收到图书转电子书或 OCR 指令时，严格按以下五阶门禁执行：

### Gate 1: 篇目切片与书型研判门禁 (Semantic Slicing & Book Profile)
1. 运行 `--doctor` 确保环境就绪；
2. 运行 `semantic_slicer.py "<PDF>"`：
   - **含原生书签**：脚本自动提取目录大纲，生成 `slice_plan.json` 并物理切片；
   - **无书签（扫描版）**：脚本自动导出前导目录页至 `preview_toc.pdf`。主 Agent 解析目录页起止页，写入 `slice_plan.json` 并追加 `--plan slice_plan.json` 切片。
3. **书型研判 (Book Profile Sensing)**：
   - 研判图书体裁：单作者专著（篇章不设署名）、多作者文集（篇章独立署名）、译作（保留译者序/随文注）；
   - 捕获用户个性意图（如“清理 CIP 版权页”、“保留题记”），沉淀为本轮动态体例上下文。
- **完成判据**：
  - `parts/*.pdf` 数量严格等于切片计划条目数（`len > 0`）；
  - `somark_jobs.json` 就绪，封面 `*_Cover.png` 已提取，书型 Profile 已确立。

### Gate 2: OCR 识别与额度保护门禁 (Batch OCR Gate)
1. **额度预警**：提示用户本次调用将消耗与切片数相同的 SoMark API 额度，获得确认后推进；
2. 运行 `somark_batch.py "<工作目录>"`：
   - 断点续跑保护：非空 Markdown 自动跳过，绝不重复计费；
   - 内部信号量限制并发 $\le 2\sim 3$，严格遵守 4 QPS 限制。
- **完成判据**：
  - `raw_md/*.md` 数量 100% 等于切片总数；
  - 每个 Markdown 文件大小 > 100 字节，`results_index.json` 中 `failed == 0`。

### Gate 3: 配图本地化门禁 (Asset Localization Gate)
1. 运行 `localize_images.py "<工作目录>"`；
2. 异步下载临时 OSS 配图至 `images/{part_stem}_fig_{idx:02d}.ext`，并替换 Markdown 中链接为相对路径。
- **完成判据**：
  - `images/` 目录下配图完整落盘（文件大小均 > 0）；
  - `localized_md/*.md` 内 100% 消除远程 `http(s)://` 图片链接。

### Gate 4: 出版级排版精修门禁 (Styling & Layout Gate - Map Phase)
依据 [references/editorial_guidelines.md](references/editorial_guidelines.md)，执行篇章精修：
- **执行模式选择**：
  - **大中体量（切片数 > 4）**：使用子智能体并行精修（参考 [references/prompt_templates.md](references/prompt_templates.md)），**主 Agent 必须将书型 Profile 与用户指令动态拼入 Prompt**；
  - **小体量（切片数 $\le 4$）**：主 Agent 可直接串行精修，保持单一上下文连贯。
- **核心排版职责**：
  1. **篇名与小节**：切片顶部确立唯一的 `## 篇章标题`；篇内小节设为 `###`；
  2. **独立序号提级**：独立成行的汉字数字（`一`、`二` ...）或阿拉伯/罗马数字，统一提级为对应小标题（如 `### 一`），且前后保留空行；
  3. **图题语义绑定**：下方具有对象性图题短句的，填入方括号 `![图题](images/...)` 并在正文中删除该单行；纯装饰图方括号留空 `![](images/...)`；
  4. **数字化去噪**：剔除 CIP 数据、条形码、定价、页眉页脚与物理页码；保留题记、序言、正文与后记。
- **完成判据**：
  - 抽查各章文件，顶部有且仅有一个 `##`；
  - 篇章小节序号完整提级，无段落粘连；图题与正文无重复。

### Gate 5: 出厂汇编与自检编译门禁 (Assembly & EPUB 3 Gate - Reduce Phase)
1. 运行 `chapter_assembler.py "<工作目录>"`：
   - 自动隔离脚注命名空间（如 `[^c01_1]`），强制规范标题前后空行；
   - 聚合生成全书主 Markdown 笔记 `《书名》.md` 与 `assembled_chapters/`；
2. 运行 `epub_builder.py "<工作目录>"`：
   - 通过 UTF-8 YAML 文件传递元数据，启用 `--shift-heading-level-by=-1` 切分多章节与生成目录；
   - 注入 `assets/styles_book.css`，后处理注入 `epub:type="noteref"` 弹框注释；
3. **主 Agent 出厂自检 (Self-Inspection Checklist)**：
   - **TOC 目录检视**：核对 EPUB 目录树，各篇标题齐整，无小节遗漏或层级坍塌；
   - **版面抽验**：抽检典型图文篇章，确认作者卡片干净、图题正常居中、去噪彻底。
- **完成判据**：
  - 工作目录下生成最终 `《书名》.epub` 与 `《书名》.md`（文件均 > 10KB）；
  - MathML 编译通过，双向弹框注释完整注入，TOC 自检通过。

---

## 资源索引

- **通用出版排版规范**：[references/editorial_guidelines.md](references/editorial_guidelines.md)（标题层级、图题契约、去噪标准与通用容器）。
- **动态派发模具**：[references/prompt_templates.md](references/prompt_templates.md)（主 Agent 动态拼接派发示例）。
- **子 Agent 提示词模具**：[references/prompts/polish_chapter.txt](references/prompts/polish_chapter.txt)（原子修润提示词）。
- **运维与故障排查**：[references/troubleshooting.md](references/troubleshooting.md)（4 QPS 限制、Windows 编码、Pandoc 章节位移）。
- **出版级样式表**：[assets/styles_book.css](assets/styles_book.css)（EPUB 3 经典书卷感 CSS）。
