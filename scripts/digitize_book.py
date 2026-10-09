#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
digitize_book.py
----------------
somark-book-epub 统一主控流水线 (Unified Master Pipeline):
1. --doctor: 全面检测运行环境 (PyMuPDF, aiohttp, Pandoc, SOMARK_API_KEY)。
2. --slice: 篇目感知与语义切片。
3. --ocr: 调用 SoMark API 批量识别。
4. --localize: 异步下载 OSS 配图并重写相对路径。
5. --assemble: 汇编篇章、隔离脚注、排版规范化。
6. --build-epub: 编译出版级 EPUB 3 与 Obsidian 主笔记。
7. 一键全自动模式: python digitize_book.py "<PDF路径>"
"""

import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).resolve().parent


def check_doctor():
    print("=" * 60)
    print("  somark-book-epub 环境与依赖体检 (Doctor Mode)")
    print("=" * 60)
    ok = True

    # Python 版本
    py_ver = sys.version.split()[0]
    print(f"[*] Python 版本: {py_ver}")

    # PyMuPDF
    try:
        import fitz
        print(f"[√] PyMuPDF (fitz): 已安装 ({fitz.__version__})")
    except ImportError:
        print("[-] PyMuPDF: 未安装！请运行: pip install PyMuPDF")
        ok = False

    # aiohttp
    try:
        import aiohttp
        print(f"[√] aiohttp: 已安装 ({aiohttp.__version__})")
    except ImportError:
        print("[-] aiohttp: 未安装！请运行: pip install aiohttp")
        ok = False

    # PIL
    try:
        import PIL
        print(f"[√] Pillow (PIL): 已安装 ({PIL.__version__})")
    except ImportError:
        print("[-] Pillow: 未安装！请运行: pip install Pillow")
        ok = False

    # Pandoc
    pandoc_exe = shutil.which("pandoc")
    if pandoc_exe:
        res = subprocess.run(["pandoc", "--version"], capture_output=True, text=True)
        first_line = res.stdout.splitlines()[0] if res.stdout else "已安装"
        print(f"[√] Pandoc: {first_line} ({pandoc_exe})")
    else:
        print("[-] Pandoc: 未找到！请安装 Pandoc 并加入 PATH")
        ok = False

    # SOMARK_API_KEY
    api_key = os.environ.get("SOMARK_API_KEY", "").strip()
    if api_key:
        print("[√] SOMARK_API_KEY: 环境变量已就绪")
    else:
        print("[!] SOMARK_API_KEY: 未配置！请设置环境变量 SOMARK_API_KEY")
        ok = False

    print("=" * 60)
    if ok:
        print("[SUCCESS] 恭喜！所有依赖均已就绪，可随时运行流水线！")
    else:
        print("[WARNING] 部分依赖缺失，请参考上方提示补全。")
    return ok


def main():
    parser = argparse.ArgumentParser(description="somark-book-epub 出版级图书数字化主控流水线")
    parser.add_argument("pdf_or_dir", nargs="?", default=None, help="输入 PDF 路径或现有工作目录")
    parser.add_argument("--doctor", action="store_true", help="检查运行环境与 API 配置")
    parser.add_argument("--slice-only", action="store_true", help="仅执行篇目感知切片")
    parser.add_argument("--ocr-only", action="store_true", help="仅执行 SoMark 批量 OCR")
    parser.add_argument("--localize-only", action="store_true", help="仅执行配图本地化下载")
    parser.add_argument("--assemble-only", action="store_true", help="仅执行篇章汇编与排版规范化")
    parser.add_argument("--epub-only", action="store_true", help="仅执行 EPUB 3 编译")
    parser.add_argument("--plan", default=None, help="自定义切片计划 JSON 路径")
    parser.add_argument("--title", default=None, help="指定图书名称")
    parser.add_argument("--author", default="读库", help="指定作者")
    parser.add_argument("--concurrency", type=int, default=2, help="SoMark API 并发数 (默认 2)")
    parser.add_argument("--force-ocr", action="store_true", help="强制重新识别已有切片")
    args = parser.parse_args()

    if args.doctor:
        sys.exit(0 if check_doctor() else 1)

    if not args.pdf_or_dir:
        parser.print_help()
        sys.exit(1)

    target_path = Path(args.pdf_or_dir).resolve()
    if not target_path.exists():
        print(f"[-] 错误：目标路径不存在: {target_path}")
        sys.exit(1)

    # 判断输入是 PDF 文件还是已有输出工作目录
    if target_path.is_file() and target_path.suffix.lower() == ".pdf":
        pdf_file = target_path
        book_title = args.title or pdf_file.stem
        work_dir = pdf_file.parent / f"{book_title}_output"
    else:
        work_dir = target_path
        book_title = args.title or work_dir.name.replace("_output", "")
        pdf_file = None

    python_exe = sys.executable

    # 1. 语义切片
    if args.slice_only or (not args.ocr_only and not args.localize_only and not args.assemble_only and not args.epub_only and pdf_file):
        print("\n" + "=" * 60)
        print(">>> 阶段 1: 篇目感知与语义切片 (Semantic Slicing)")
        print("=" * 60)
        cmd = [python_exe, str(SCRIPT_DIR / "semantic_slicer.py"), str(pdf_file), "-o", str(work_dir)]
        if args.plan:
            cmd.extend(["--plan", args.plan])
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print("[-] 切片阶段未完成或需外部计划，退出。")
            sys.exit(res.returncode)
        if args.slice_only:
            print("[*] 仅切片模式完成。")
            sys.exit(0)

    # 2. 批量 SoMark OCR
    if args.ocr_only or (not args.slice_only and not args.localize_only and not args.assemble_only and not args.epub_only):
        print("\n" + "=" * 60)
        print(">>> 阶段 2: SoMark 批量高保真识别 (Batch OCR)")
        print("=" * 60)
        cmd = [python_exe, str(SCRIPT_DIR / "somark_batch.py"), str(work_dir), "--concurrency", str(args.concurrency)]
        if args.force_ocr:
            cmd.append("--force")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print("[-] OCR 阶段失败，退出。")
            sys.exit(res.returncode)
        if args.ocr_only:
            print("[*] 仅 OCR 模式完成。")
            sys.exit(0)

    # 3. 远程配图本地化下载
    if args.localize_only or (not args.slice_only and not args.ocr_only and not args.assemble_only and not args.epub_only):
        print("\n" + "=" * 60)
        print(">>> 阶段 3: 配图本地化下载与相对路径重写 (Image Localization)")
        print("=" * 60)
        cmd = [python_exe, str(SCRIPT_DIR / "localize_images.py"), str(work_dir)]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print("[-] 配图本地化阶段失败，退出。")
            sys.exit(res.returncode)
        if args.localize_only:
            print("[*] 仅配图本地化模式完成。")
            sys.exit(0)

    # 4. 汇编篇章
    if args.assemble_only or (not args.slice_only and not args.ocr_only and not args.localize_only and not args.epub_only):
        print("\n" + "=" * 60)
        print(">>> 阶段 4: 篇章汇编与排版规范化 (Assembly & Footnote Isolation)")
        print("=" * 60)
        cmd = [python_exe, str(SCRIPT_DIR / "chapter_assembler.py"), str(work_dir), "--title", book_title]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print("[-] 篇章汇编阶段失败，退出。")
            sys.exit(res.returncode)
        if args.assemble_only:
            print("[*] 仅汇编模式完成。")
            sys.exit(0)

    # 5. 编译出版级 EPUB 3
    if args.epub_only or (not args.slice_only and not args.ocr_only and not args.localize_only and not args.assemble_only):
        print("\n" + "=" * 60)
        print(">>> 阶段 5: Pandoc 出版级 EPUB 3 编译 (EPUB 3 Building)")
        print("=" * 60)
        cmd = [
            python_exe,
            str(SCRIPT_DIR / "epub_builder.py"),
            str(work_dir),
            "--title", book_title,
            "--author", args.author
        ]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print("[-] EPUB 编译阶段失败，退出。")
            sys.exit(res.returncode)

    print("\n" + "=" * 60)
    print(f"[FINISHED] 全流程构建完成！电子书与笔记已输出至: {work_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
