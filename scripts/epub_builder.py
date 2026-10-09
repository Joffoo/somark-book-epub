#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
epub_builder.py
---------------
出版级 EPUB 3 与 Obsidian 典藏笔记构建引擎：
1. 查找并调用 Pandoc 编译器。
2. 注入出版级书卷风 CSS (styles_book.css)。
3. 支持 MathML 自适应公式、封面绑定、双向弹框注释 (popup footnotes)。
4. XHTML 后处理：注入 epub:type="noteref"、<aside epub:type="footnote" class="footnote-popup">。
5. 生成包含 YAML 属性的 Obsidian Master Note。
"""

import os
import sys
import re
import shutil
import zipfile
import subprocess
import argparse
import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')


def find_pandoc():
    p = shutil.which('pandoc')
    if p:
        return p
    std_candidates = []
    if os.name == 'nt':
        local_appdata = os.environ.get('LOCALAPPDATA', '')
        program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
        program_files_x86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
        std_candidates.extend([
            os.path.join(program_files, 'Pandoc', 'pandoc.exe'),
            os.path.join(program_files_x86, 'Pandoc', 'pandoc.exe'),
            os.path.join(local_appdata, 'Pandoc', 'pandoc.exe'),
        ])
    elif sys.platform == 'darwin':
        std_candidates.extend(['/usr/local/bin/pandoc', '/opt/homebrew/bin/pandoc'])
    elif sys.platform.startswith('linux'):
        std_candidates.extend(['/usr/bin/pandoc', '/usr/local/bin/pandoc'])
    for c in std_candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("未找到 Pandoc 可执行文件！请确认 Pandoc 已安装并加入环境变量。")


def build_epub_and_master(
    title: str,
    author: str,
    chapter_paths: list[str],
    cover_image: str,
    out_epub: str,
    out_master_md: str = None,
    translator: str = None,
    publisher: str = None,
    css_path: str = None,
    front_matter_md: str = None,
    resource_path: list[str] = None,
    tags: list[str] = None
):
    pandoc_exe = find_pandoc()
    print(f"[*] 检测到 Pandoc: {pandoc_exe}")

    if css_path is None:
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        css_path = os.path.join(skill_root, 'assets', 'styles_book.css')

    if not os.path.exists(css_path):
        raise FileNotFoundError(f"未找到样式表文件: {css_path}")

    # 1. 构建 Obsidian Master Note
    if out_master_md:
        print(f"[*] 生成全书主笔记: {out_master_md}")
        tag_list = tags or ['书籍', '电子书', 'SoMark']
        tag_yaml = "\n".join(f"  - {t}" for t in tag_list)
        cover_fn = os.path.basename(cover_image) if cover_image else ""
        header = f"""---
title: {title}
author: "{author}"
{f'translator: "{translator}"' if translator else ''}
date: {datetime.date.today().isoformat()}
tags:
{tag_yaml}
{f'cover: "[[{cover_fn}]]"' if cover_fn else ''}
---

{f'![[{cover_fn}|400]]' if cover_fn else ''}

"""
        with open(out_master_md, 'w', encoding='utf-8') as f_out:
            f_out.write(header)
            if front_matter_md and os.path.exists(front_matter_md):
                with open(front_matter_md, 'r', encoding='utf-8') as f_fm:
                    f_out.write(f_fm.read() + "\n\n---\n\n")
            for cp in chapter_paths:
                with open(cp, 'r', encoding='utf-8') as f_c:
                    f_out.write(f_c.read() + "\n\n---\n\n")
        print(f"[OK] 全书笔记已落盘 ({os.path.getsize(out_master_md)} 字节)")

    # 2. 调用 Pandoc 编译 EPUB 3
    out_dir = os.path.dirname(os.path.abspath(out_epub))
    raw_epub = out_epub + '.tmp.epub'

    # 使用 UTF-8 YAML metadata 文件，彻底避免 Windows 命令行传参导致的编码乱码
    meta_file = os.path.join(out_dir, "pandoc_meta.yaml")
    meta_lines = [
        "---",
        f"title: \"{title}\"",
        f"creator:",
        f"  - role: author",
        f"    text: \"{author}\"",
        "language: zh-CN"
    ]
    if translator:
        meta_lines.append(f"  - role: translator\n    text: \"{translator}\"")
    if publisher:
        meta_lines.append(f"publisher: \"{publisher}\"")
    meta_lines.append("...")
    with open(meta_file, 'w', encoding='utf-8') as f_meta:
        f_meta.write("\n".join(meta_lines) + "\n")

    cmd = [
        pandoc_exe,
        '-s',
        '-o', raw_epub,
        '--from=markdown+smart+footnotes',
        '--to=epub3',
        '--mathml',
        f'--metadata-file={meta_file}',
        '--shift-heading-level-by=-1',
        '--toc',
        '--toc-depth=1',
        '--split-level=1',
        '--epub-title-page=false'
    ]
    if cover_image and os.path.exists(cover_image):
        cmd.extend([f'--epub-cover-image={cover_image}'])
    if css_path and os.path.exists(css_path):
        cmd.extend([f'--css={css_path}'])

    res_dirs = []
    if resource_path:
        res_dirs.extend(resource_path if isinstance(resource_path, (list, tuple)) else [resource_path])

    out_dir = os.path.dirname(os.path.abspath(out_epub))
    res_dirs.append(out_dir)
    res_dirs.append(os.path.join(out_dir, "images"))
    if chapter_paths and os.path.exists(chapter_paths[0]):
        ch_dir = os.path.dirname(os.path.abspath(chapter_paths[0]))
        res_dirs.append(ch_dir)
        res_dirs.append(os.path.join(ch_dir, "images"))

    valid_res = []
    for rd in res_dirs:
        if os.path.exists(rd) and rd not in valid_res:
            valid_res.append(rd)
    if valid_res:
        sep = ';' if os.name == 'nt' else ':'
        cmd.extend([f'--resource-path={sep.join(valid_res)}'])

    cmd.extend(chapter_paths)

    print(f"[*] 启动 Pandoc 编译 EPUB 3 ({len(chapter_paths)} 个章节)...")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if res.returncode != 0:
        print("Pandoc 错误信息:", res.stderr)
        raise RuntimeError("Pandoc 编译 EPUB 失败！")

    print(f"[OK] Pandoc 基础编译完成 ({os.path.getsize(raw_epub)} 字节)")

    # 3. EPUB XHTML 后处理：注入双向弹框注释与图注
    print("[*] 后处理 XHTML：注入 EPUB 3 弹框气泡注释语义...")
    with open(css_path, 'r', encoding='utf-8') as f:
        css_content = f.read()

    files_data = {}
    with zipfile.ZipFile(raw_epub, 'r') as zin:
        for name in zin.namelist():
            files_data[name] = zin.read(name)

    # 替换样式表
    for name in list(files_data.keys()):
        if name.endswith('.css'):
            files_data[name] = css_content.encode('utf-8')

    for name in list(files_data.keys()):
        if name.endswith(('.xhtml', '.html')) and not name.endswith('nav.xhtml'):
            text = files_data[name].decode('utf-8', errors='ignore')

            # 图注转换
            text = re.sub(
                r'<p><img\s+src="([^"]+)"\s+alt=""\s*/>\s*<em>(.*?)</em></p>',
                r'<figure>\n<img src="\1" alt="\2" />\n<figcaption>\2</figcaption>\n</figure>',
                text
            )

            # 注入双向气泡注释
            text = re.sub(r'<aside\s+([^>]*epub:type="footnote"[^>]*)>', r'<aside \1 class="footnote-popup">', text)
            text = re.sub(r'<a\s+([^>]*epub:type="noteref"[^>]*)>', r'<a \1 class="noteref">', text)

            # 题记与序诗样式
            if re.search(r'id="[^"]*题记[^"]*"', text) or re.search(r'<h1[^>]*>.*?题记.*?</h1>', text):
                text = re.sub(r'(<section\s+[^>]*class="[^"]*)(")', r'\1 epigraph-section\2', text)
                text = re.sub(r'<section(?!\s+[^>]*class=)([^>]*)>', r'<section class="epigraph-section"\1>', text)
                text = re.sub(r'(<h1\s+class="[^"]*)(")', r'\1 epigraph-title" style="display:none;\2', text, count=1)
                text = re.sub(r'<h1(?!\s+class=)([^>]*)>', r'<h1 class="epigraph-title" style="display:none;"\1>', text, count=1)
                text = re.sub(r'<p(?!\s+class=)>', r'<p class="poem-stanza">', text)

            files_data[name] = text.encode('utf-8')
        elif name.endswith('nav.xhtml'):
            nav_text = files_data[name].decode('utf-8', errors='ignore')
            nav_text = re.sub(r'<a\s+([^>]*)>([^<]*)<a[^>]*class="footnote-ref"[^>]*>.*?</a>(.*?)</a>', r'<a \1>\2\3</a>', nav_text)
            files_data[name] = nav_text.encode('utf-8')

    # 保存最终 EPUB 3
    os.makedirs(os.path.dirname(os.path.abspath(out_epub)), exist_ok=True)
    with zipfile.ZipFile(out_epub, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        if 'mimetype' in files_data:
            zout.writestr('mimetype', files_data['mimetype'], compress_type=zipfile.ZIP_STORED)
        for name, data in files_data.items():
            if name != 'mimetype':
                zout.writestr(name, data)

    if os.path.exists(raw_epub):
        os.remove(raw_epub)

    print(f"\n[SUCCESS] EPUB 3 典藏电子书构建成功！")
    print(f"[*] 输出路径: {out_epub} ({os.path.getsize(out_epub)} 字节)")


def main():
    parser = argparse.ArgumentParser(description="出版级 EPUB 3 构建工具")
    parser.add_argument("work_dir", help="工作目录路径 (包含 assembled_chapters/)")
    parser.add_argument("--title", default=None, help="书名")
    parser.add_argument("--author", default="读库", help="作者")
    parser.add_argument("--cover", default=None, help="封面图片路径")
    parser.add_argument("--out-epub", default=None, help="输出 EPUB 路径")
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    assembled_dir = work_dir / "assembled_chapters"
    if not assembled_dir.exists():
        print(f"[-] 错误：未找到 assembled_chapters 目录: {assembled_dir}")
        sys.exit(1)

    chapter_files = sorted(str(p) for p in assembled_dir.glob("*.md"))
    if not chapter_files:
        print(f"[-] 错误：assembled_chapters 中没有 .md 文件")
        sys.exit(1)

    title = args.title or work_dir.name.replace("_output", "")
    out_epub = args.out_epub or str(work_dir / f"{title}.epub")
    out_master_md = str(work_dir / f"{title}.md")

    cover = args.cover
    if not cover:
        # 自动探测封面
        cov_candidates = list(work_dir.glob("*_Cover.png")) + list(work_dir.glob("cover.*"))
        if cov_candidates:
            cover = str(cov_candidates[0])

    build_epub_and_master(
        title=title,
        author=args.author,
        chapter_paths=chapter_files,
        cover_image=cover,
        out_epub=out_epub,
        out_master_md=out_master_md
    )


if __name__ == "__main__":
    main()
