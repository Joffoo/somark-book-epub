#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chapter_assembler.py
--------------------
出版级篇章汇编与排版规范化引擎：
1. 读取 localized_md/ 中的篇章 Markdown。
2. 隔离各篇目脚注命名空间（[^c01_1]...），杜绝全书交叉碰撞。
3. 排版流式纯化：
   - 修复列表前后缺少空行导致的排版坍塌。
   - 规范全角中文标点与英文标点。
   - 确保图片块前后空行，保证 Pandoc <figure><figcaption> 正常生成。
4. 确保每篇具备规范的大章标题（## 篇目标题）与作者署名。
5. 导出独立汇编章节 (assembled_chapters/) 与全书主笔记 (《书名》.md)。
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')


def isolate_footnotes(text: str, prefix: str) -> str:
    """
    给当前篇章所有脚注加前缀，如 [^1] -> [^c01_1]，[^1]: -> [^c01_1]:
    """
    def repl_def(m):
        fn_id = m.group(1)
        return f"[^{prefix}_{fn_id}]:"

    def repl_ref(m):
        fn_id = m.group(1)
        return f"[^{prefix}_{fn_id}]"

    text = re.sub(r'\[\^([^\]]+)\]:', repl_def, text)
    text = re.sub(r'\[\^([^\]]+)\](?!\:)', repl_ref, text)
    return text


def normalize_text_layout(text: str) -> str:
    """出版级 Markdown 版面清洗与标准化"""
    # 剥除外层包裹的代码块
    text = re.sub(r'^```markdown\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'```$', '', text.strip(), flags=re.MULTILINE)

    # 1. 列表前后强制空行
    text = re.sub(r'([^\n])\n((?:[-*+]|\d+[\.\)])\s+[^\n]+)', r'\1\n\n\2', text)
    text = re.sub(r'(\n(?:[-*+]|\d+[\.\)])\s+[^\n]+)\n+([^-\d*+\n\s])', r'\1\n\n\2', text)

    # 2. 标点全角化规范（中文之间的半角标点转全角）
    text = re.sub(r'([\u4e00-\u9fa5]),([\u4e00-\u9fa5\s])', r'\1，\2', text)
    text = re.sub(r'([\u4e00-\u9fa5]);([\u4e00-\u9fa5\s])', r'\1；\2', text)
    text = re.sub(r'([\u4e00-\u9fa5]):([\u4e00-\u9fa5])', r'\1：\2', text)
    text = re.sub(r'([\u4e00-\u9fa5])\(([\d\u4e00-\u9fa5]+)\)(?!\])', r'\1（\2）', text)

    # 3. 图片前后强制空行
    text = re.sub(r'([^\n])\n(!\[[^\]]*\]\([^)]+\))', r'\1\n\n\2', text)
    text = re.sub(r'(!\[[^\]]*\]\([^)]+\))\n+([^\n*])', r'\1\n\n\2', text)

    # 4. 标题前后强制空行（CommonMark / Pandoc 语法规范）
    text = re.sub(r'([^\n])\n(#{1,6}\s+[^\n]+)', r'\1\n\n\2', text)
    text = re.sub(r'(#{1,6}\s+[^\n]+)\n([^\n#])', r'\1\n\n\2', text)

    # 5. 连续 3 个以上换行压缩为 2 个换行
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def ensure_chapter_heading(text: str, title: str) -> str:
    """
    确保篇章头部具备规范的二级标题 ## 篇目标题
    """
    lines = text.splitlines()
    has_h2 = False
    for line in lines[:5]:
        if line.strip().startswith('## '):
            has_h2 = True
            break

    if not has_h2 and title:
        # 在顶部补全 ## 篇目标题
        text = f"## {title}\n\n" + text.lstrip()

    return text


def assemble_chapters(work_dir: Path, book_title: str = None) -> list[Path]:
    work_dir = Path(work_dir).resolve()
    # 优先使用已下载本地配图的 localized_md，没有则回退 raw_md
    src_dir = work_dir / "localized_md"
    if not src_dir.exists() or not list(src_dir.glob("*.md")):
        src_dir = work_dir / "raw_md"

    if not src_dir.exists():
        print(f"[-] 错误：未找到 Markdown 来源目录 (localized_md 或 raw_md)")
        sys.exit(1)

    assembled_dir = work_dir / "assembled_chapters"
    assembled_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(src_dir.glob("*.md"))
    if not md_files:
        print(f"[-] 错误：{src_dir} 中没有找到 .md 文件")
        sys.exit(1)

    # 读取 somark_jobs.json 以获取规范标题
    jobs_manifest = work_dir / "somark_jobs.json"
    job_titles = {}
    if jobs_manifest.exists():
        try:
            with open(jobs_manifest, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not book_title:
                    book_title = data.get("book_title")
                for j in data.get("jobs", []):
                    idx = j.get("part_index")
                    if idx:
                        job_titles[idx] = j.get("title", "")
        except Exception:
            pass

    if not book_title:
        book_title = work_dir.name.replace("_output", "")

    assembled_paths = []
    full_book_chunks = []

    print(f"[*] 开始汇编篇章 (来源: {src_dir.name})...")
    for i, md_file in enumerate(md_files, 1):
        content = md_file.read_text(encoding='utf-8')
        title = job_titles.get(i, md_file.stem)

        # 1. 规范化排版
        clean_text = normalize_text_layout(content)

        # 2. 隔离脚注命名空间
        clean_text = isolate_footnotes(clean_text, f"c{i:02d}")

        # 3. 确保包含二级标题
        clean_text = ensure_chapter_heading(clean_text, title)

        # 写入 assembled_chapters
        out_chapter_name = f"{i:02d}_{md_file.stem}.md"
        out_chapter_path = assembled_dir / out_chapter_name
        out_chapter_path.write_text(clean_text, encoding='utf-8')
        assembled_paths.append(out_chapter_path)
        full_book_chunks.append(clean_text)

        print(f"  [+] 汇编篇章: {out_chapter_name}")

    # 合并为全书主 Markdown
    master_md_path = work_dir / f"{book_title}.md"
    master_content = f"# {book_title}\n\n" + "\n\n---\n\n".join(full_book_chunks) + "\n"
    master_md_path.write_text(master_content, encoding='utf-8')
    print(f"\n[*] 全书主笔记已生成: {master_md_path}")
    print(f"[*] 独立篇章目录: {assembled_dir}")

    return assembled_paths


def main():
    parser = argparse.ArgumentParser(description="出版级篇章汇编引擎")
    parser.add_argument("work_dir", help="工作目录路径")
    parser.add_argument("--title", default=None, help="图书书名（默认由工作目录名推导）")
    args = parser.parse_args()

    assemble_chapters(Path(args.work_dir), book_title=args.title)


if __name__ == "__main__":
    main()
