#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
somark_batch.py
----------------
SoMark 批量异步识别引擎：
1. 读取 somark_jobs.json 或 parts/ 目录。
2. 调度 SoMark API 批量识别（并发控制 <= 2~3，严格遵守 4 QPS 限制）。
3. 支持断点续跑：已存在 Markdown 结果的切片自动跳过，绝不浪费用户 API 额度。
4. 结构化保存 raw_md/*.md 与 raw_json/*.json。
5. 生成全局 results_index.json 供流水线审计。
"""

import os
import sys
import time
import json
import asyncio
import argparse
from pathlib import Path
from typing import Any
import aiohttp

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_BASE_URL = "https://somark.cn/api/v1"
DEFAULT_OUTPUT_FORMATS = ["markdown", "json"]
DEFAULT_ELEMENT_FORMATS = {
    "image": "url",
    "formula": "latex",
    "table": "html",
    "cs": "image"
}
DEFAULT_FEATURE_CONFIG = {
    "enable_text_cross_page": True,
    "enable_table_cross_page": True,
    "enable_title_level_recognition": True,
    "enable_inline_image": True,
    "enable_table_image": True,
    "enable_image_understanding": True,
    "keep_header_footer": False
}


async def submit_task(
    session: aiohttp.ClientSession,
    file_path: Path,
    api_key: str,
    async_url: str,
    output_formats: list[str],
    element_formats: dict[str, str],
    feature_config: dict[str, bool]
) -> str:
    data = aiohttp.FormData(quote_fields=False)
    data.add_field("api_key", api_key)
    filename = file_path.name
    data.add_field("file", file_path.read_bytes(), filename=filename)
    for fmt in output_formats:
        data.add_field("output_formats", fmt)
    data.add_field("element_formats", json.dumps(element_formats, ensure_ascii=False))
    data.add_field("feature_config", json.dumps(feature_config, ensure_ascii=False))

    async with session.post(async_url, data=data) as resp:
        if resp.status != 200:
            err = await resp.text()
            raise RuntimeError(f"提交任务失败 [{resp.status}]: {err}")
        body = await resp.json()

    task_id = (body.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"响应中未找到 task_id: {body}")
    return task_id


async def poll_task(
    session: aiohttp.ClientSession,
    task_id: str,
    api_key: str,
    check_url: str,
    max_retries: int = 400,
    interval: int = 3
) -> dict[str, Any]:
    for _ in range(max_retries):
        await asyncio.sleep(interval)
        async with session.post(
            check_url, data={"api_key": api_key, "task_id": task_id}
        ) as resp:
            if resp.status != 200:
                continue
            body = await resp.json()

        data = body.get("data") or {}
        status = data.get("status")
        if status == "FAILED":
            raise RuntimeError(f"SoMark 解析失败: {data}")
        if status == "SUCCESS":
            return body

    raise TimeoutError(f"SoMark 轮询超时: task_id={task_id}")


async def process_single_job(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    job: dict,
    api_key: str,
    async_url: str,
    check_url: str,
    force: bool = False
) -> dict:
    pdf_path = Path(job["pdf_path"])
    raw_md_path = Path(job["raw_md_path"])
    raw_json_path = Path(job["raw_json_path"])

    # 断点续跑保护
    if not force and raw_md_path.exists() and raw_md_path.stat().st_size > 100:
        print(f"  [SKIP] 已存在解析结果，跳过节省额度: {pdf_path.name}")
        return {
            "status": "cached",
            "file": str(pdf_path),
            "markdown": str(raw_md_path),
            "json": str(raw_json_path) if raw_json_path.exists() else None,
            "title": job.get("title", "")
        }

    async with semaphore:
        print(f"\n[*] 开始解析: {pdf_path.name} ({job.get('title', '')})")
        t0 = time.time()
        try:
            task_id = await submit_task(
                session,
                pdf_path,
                api_key,
                async_url,
                DEFAULT_OUTPUT_FORMATS,
                DEFAULT_ELEMENT_FORMATS,
                DEFAULT_FEATURE_CONFIG
            )
            print(f"  [-] 任务已提交 (task_id={task_id})，等待结果...")
            response = await poll_task(session, task_id, api_key, check_url)

            result_outputs = ((response.get("data") or {}).get("result") or {}).get("outputs") or {}
            md_text = result_outputs.get("markdown", "")
            if not md_text:
                raise RuntimeError("API 返回数据中缺少 markdown 内容")

            # 保存 Markdown 与完整 JSON
            raw_md_path.parent.mkdir(parents=True, exist_ok=True)
            raw_json_path.parent.mkdir(parents=True, exist_ok=True)
            raw_md_path.write_text(md_text, encoding="utf-8")
            raw_json_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

            elapsed = round(time.time() - t0, 2)
            meta = (response.get("data") or {}).get("metadata") or {}
            pages = meta.get("page_num", 0)
            print(f"  [SUCCESS] 解析完成: {pdf_path.name} | 页数: {pages} | 耗时: {elapsed}s")

            return {
                "status": "success",
                "file": str(pdf_path),
                "markdown": str(raw_md_path),
                "json": str(raw_json_path),
                "title": job.get("title", ""),
                "pages": pages,
                "elapsed": elapsed
            }
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            print(f"  [FAILED] 解析失败: {pdf_path.name} | 错误: {e}")
            return {
                "status": "failed",
                "file": str(pdf_path),
                "title": job.get("title", ""),
                "error": str(e),
                "elapsed": elapsed
            }


async def run_batch(work_dir: Path, force: bool = False, concurrency: int = 2):
    api_key = os.environ.get("SOMARK_API_KEY", "").strip()
    if not api_key:
        print("[-] 错误：未检测到环境变量 SOMARK_API_KEY，请先设置后再运行！")
        sys.exit(1)

    base_url = (os.environ.get("SOMARK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    async_url = f"{base_url}/parse/async"
    check_url = f"{base_url}/parse/async_check"

    jobs_file = work_dir / "somark_jobs.json"
    if jobs_file.exists():
        with open(jobs_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        jobs = manifest.get("jobs", [])
    else:
        # 兼容无 jobs.json 场景：直接扫描 parts 目录
        parts_dir = work_dir / "parts"
        if not parts_dir.exists():
            print(f"[-] 错误：未找到 {jobs_file} 或 {parts_dir}")
            sys.exit(1)
        pdf_files = sorted(parts_dir.glob("*.pdf"))
        jobs = []
        for i, pf in enumerate(pdf_files, 1):
            stem = pf.stem
            jobs.append({
                "part_index": i,
                "title": stem,
                "pdf_path": str(pf),
                "raw_md_path": str(work_dir / "raw_md" / f"{stem}.md"),
                "raw_json_path": str(work_dir / "raw_json" / f"{stem}.json")
            })

    print(f"[*] 发现 {len(jobs)} 个待处理篇目任务")
    print(f"[*] 并发限制: {concurrency} (遵循 4 QPS 限制)")

    semaphore = asyncio.Semaphore(concurrency)
    results = []

    async with aiohttp.ClientSession() as session:
        tasks = [
            process_single_job(session, semaphore, job, api_key, async_url, check_url, force=force)
            for job in jobs
        ]
        results = await asyncio.gather(*tasks)

    # 保存总结果索引
    index_file = work_dir / "results_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success_cnt = sum(1 for r in results if r["status"] in ("success", "cached"))
    failed_cnt = sum(1 for r in results if r["status"] == "failed")
    print(f"\n[*] 批处理完成：成功/命中缓存 {success_cnt} 个，失败 {failed_cnt} 个")
    print(f"[*] 结果索引文件: {index_file}")

    if failed_cnt > 0:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="SoMark 批量异步识别工具")
    parser.add_argument("work_dir", help="工作目录路径 (包含 parts/ 与 somark_jobs.json)")
    parser.add_argument("--force", action="store_true", help="强制重新识别已存在的切片")
    parser.add_argument("--concurrency", type=int, default=2, help="并发数量 (默认 2，最大建议 3)")
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    if not work_dir.exists():
        print(f"[-] 错误：工作目录不存在: {work_dir}")
        sys.exit(1)

    asyncio.run(run_batch(work_dir, force=args.force, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
