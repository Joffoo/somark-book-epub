#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
localize_images.py
-------------------
远程配图本地化引擎 (Deterministic Asset Pipeline)：
1. 遍历 raw_md/*.md 中的所有远程图片链接（如 SoMark 托管在阿里云 OSS 的配图）。
2. 高速异步并发下载图片资产至本地 images/ 目录。
3. 纯确定性重写图片 URL 为相对路径 images/{part_stem}_fig_{idx:02d}.ext。
4. 绝不在代码中硬编码语义判断，正文拓扑与图题语义 100% 交由 Agent 自主裁决。
5. 保存本地化后的 Markdown 至 localized_md/ 目录。
"""

import os
import sys
import re
import asyncio
from pathlib import Path
from urllib.parse import urlparse
import aiohttp

sys.stdout.reconfigure(encoding='utf-8')

# 匹配 Markdown 图片与 HTML <img>
MD_IMG_PATTERN = re.compile(r'!\[([\s\S]*?)\]\((https?://[^\)\s]+)\)')
HTML_IMG_PATTERN = re.compile(r'<img\s+[^>]*src=["\'](https?://[^"\']+)["\'][^>]*>', re.IGNORECASE)


def get_extension(url: str, content_type: str = "") -> str:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg']:
        return ext
    if 'jpeg' in content_type or 'jpg' in content_type:
        return '.jpg'
    if 'png' in content_type:
        return '.png'
    if 'webp' in content_type:
        return '.webp'
    return '.jpg'


async def download_image(
    session: aiohttp.ClientSession,
    url: str,
    out_path: Path,
    max_retries: int = 3
) -> bool:
    if out_path.exists() and out_path.stat().st_size > 0:
        return True

    for attempt in range(max_retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(data)
                    return True
                else:
                    print(f"  [-] 下载失败 [{resp.status}]: {url}")
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"  [-] 下载异常 ({url}): {e}")
            await asyncio.sleep(1)
    return False


async def process_file(
    session: aiohttp.ClientSession,
    md_file: Path,
    images_dir: Path,
    out_file: Path
) -> tuple[int, int]:
    content = md_file.read_text(encoding='utf-8')
    part_stem = md_file.stem

    # 提取所有图片 URL
    matches = MD_IMG_PATTERN.findall(content)
    # matches: [(alt, url), ...]

    url_to_local = {}
    fig_counter = 1

    download_tasks = []
    task_keys = []

    for alt, url in matches:
        if url in url_to_local:
            continue
        ext = get_extension(url)
        img_filename = f"{part_stem}_fig_{fig_counter:02d}{ext}"
        local_target = images_dir / img_filename
        url_to_local[url] = f"images/{img_filename}"
        fig_counter += 1

        download_tasks.append(download_image(session, url, local_target))
        task_keys.append(url)

    # 并发下载
    if download_tasks:
        results = await asyncio.gather(*download_tasks)
        success_cnt = sum(1 for r in results if r)
    else:
        success_cnt = 0

    # 仅执行确定性路径重写，绝不修改正文内容与语义
    def repl_md(match):
        alt = match.group(1)
        url = match.group(2)
        local_rel = url_to_local.get(url, url)
        return f"![{alt}]({local_rel})"

    new_content = MD_IMG_PATTERN.sub(repl_md, content)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(new_content, encoding='utf-8')

    return len(matches), success_cnt


async def run_localization(work_dir: Path):
    raw_md_dir = work_dir / "raw_md"
    localized_md_dir = work_dir / "localized_md"
    images_dir = work_dir / "images"

    if not raw_md_dir.exists():
        print(f"[-] 错误：未找到 raw_md 目录: {raw_md_dir}")
        sys.exit(1)

    images_dir.mkdir(parents=True, exist_ok=True)
    localized_md_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(raw_md_dir.glob("*.md"))
    print(f"[*] 发现 {len(md_files)} 个 Markdown 文件待本地化配图")

    total_images = 0
    total_downloaded = 0

    async with aiohttp.ClientSession() as session:
        for md_f in md_files:
            out_f = localized_md_dir / md_f.name
            imgs_found, imgs_done = await process_file(session, md_f, images_dir, out_f)
            total_images += imgs_found
            total_downloaded += imgs_done
            if imgs_found > 0:
                print(f"  [+] {md_f.name}: 提取并下载 {imgs_done}/{imgs_found} 张配图")

    print(f"\n[*] 配图本地化下载完成！共发现 {total_images} 张图片，成功下载并重写 {total_downloaded} 张。")
    print(f"[*] 本地化 Markdown 已输出至: {localized_md_dir}")
    print("[*] 提示：图题语义、大标题层级与作者卡片请由 Agent / Subagent 基于语义自主校对。")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="远程配图本地化下载与相对路径重写工具")
    parser.add_argument("work_dir", help="工作目录路径")
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    if not work_dir.exists():
        print(f"[-] 错误：工作目录不存在: {work_dir}")
        sys.exit(1)

    asyncio.run(run_localization(work_dir))


if __name__ == "__main__":
    main()
