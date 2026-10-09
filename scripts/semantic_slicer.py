#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semantic_slicer.py
-------------------
PDF 篇目感知与语义切片引擎：
1. 自动提取 PDF 书签大纲 (Bookmarks / Outline)。
2. 若存在大纲，自动生成篇目切片计划 (slice_plan.json)。
3. 若无书签大纲，提取封面与目录候选页，支持外部 plan 注入切片。
4. 按真实篇目边界（物理边界 = 语义边界）切分为微型 PDF 并导出封面。
5. 生成 somark_jobs.json 任务清单供 SoMark 批量识别。
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
import fitz  # PyMuPDF

sys.stdout.reconfigure(encoding='utf-8')


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = re.sub(r'\s+', '_', name).strip('_. ')
    return name[:60] if len(name) > 60 else (name or "chapter")


def extract_cover(doc: fitz.Document, out_path: str, dpi: int = 300) -> bool:
    """提取第 1 页作为高清封面"""
    if len(doc) == 0:
        return False
    try:
        page = doc[0]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        pix.save(out_path)
        print(f"[*] 封面已提取 (DPI {dpi}): {out_path}")
        return True
    except Exception as e:
        print(f"[-] 封面提取失败: {e}")
        return False


def get_pdf_outline(doc: fitz.Document):
    """
    获取 PDF 原生书签目录:
    返回格式: [[level, title, page_1based], ...]
    """
    toc = doc.get_toc()
    if not toc:
        return []
    cleaned_toc = []
    for item in toc:
        lvl, title, page = item[0], item[1].strip(), item[2]
        if page > 0 and page <= len(doc) and title:
            cleaned_toc.append([lvl, title, page])
    return cleaned_toc


def generate_plan_from_outline(toc: list, total_pages: int, min_pages: int = 1) -> list[dict]:
    """
    从书签目录智能构建篇目切片计划
    """
    if not toc:
        return []

    # 确定大章的基准 level（通常是 1，如果 level 1 只有一条且是全书书名，则选 level 2）
    level_counts = {}
    for lvl, _, _ in toc:
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    target_lvl = 1
    if level_counts.get(1, 0) <= 1 and level_counts.get(2, 0) > 1:
        target_lvl = 2

    # 提取目标 level 的条目
    entries = []
    for lvl, title, page in toc:
        if lvl == target_lvl:
            entries.append({"title": title, "page": page})

    if not entries:
        # 降级：直接取所有条目
        entries = [{"title": t, "page": p} for _, t, p in toc]

    # 去重并按页码排序
    entries.sort(key=lambda x: x["page"])
    deduped = []
    for e in entries:
        if not deduped or deduped[-1]["page"] != e["page"]:
            deduped.append(e)

    plan = []
    # 如果第一章不在第 1 页，前置页作为“前言/目录”片
    if deduped and deduped[0]["page"] > 1:
        plan.append({
            "part_index": 1,
            "title": "卷首与目录",
            "start_page": 1,
            "end_page": deduped[0]["page"] - 1,
            "page_count": deduped[0]["page"] - 1
        })

    for i, e in enumerate(deduped):
        part_idx = len(plan) + 1
        start_p = e["page"]
        if i + 1 < len(deduped):
            end_p = deduped[i + 1]["page"] - 1
        else:
            end_p = total_pages

        if end_p < start_p:
            end_p = start_p

        plan.append({
            "part_index": part_idx,
            "title": e["title"],
            "start_page": start_p,
            "end_page": end_p,
            "page_count": end_p - start_p + 1
        })

    return plan


def slice_pdf(pdf_path: str, plan: list[dict], out_work_dir: str) -> list[dict]:
    """
    根据切片计划执行物理 PDF 切割
    """
    doc = fitz.open(pdf_path)
    parts_dir = os.path.join(out_work_dir, "parts")
    os.makedirs(parts_dir, exist_ok=True)

    jobs = []
    for item in plan:
        idx = item["part_index"]
        title = item["title"]
        start_p = item["start_page"]
        end_p = item["end_page"]
        safe_title = sanitize_filename(title)

        out_pdf_name = f"part_{idx:02d}_{safe_title}.pdf"
        out_pdf_path = os.path.join(parts_dir, out_pdf_name)

        # 0-based 范围截取
        start_0 = max(0, start_p - 1)
        end_0 = min(len(doc) - 1, end_p - 1)

        part_doc = fitz.open()
        part_doc.insert_pdf(doc, from_page=start_0, to_page=end_0)
        part_doc.save(out_pdf_path)
        part_doc.close()

        job_info = {
            "part_index": idx,
            "title": title,
            "start_page": start_p,
            "end_page": end_p,
            "page_count": end_0 - start_0 + 1,
            "pdf_path": out_pdf_path,
            "pdf_filename": out_pdf_name,
            "raw_md_path": os.path.join(out_work_dir, "raw_md", f"part_{idx:02d}_{safe_title}.md"),
            "raw_json_path": os.path.join(out_work_dir, "raw_json", f"part_{idx:02d}_{safe_title}.json")
        }
        jobs.append(job_info)
        print(f"  [+] 已切片: {out_pdf_name} (第 {start_p}~{end_p} 页, 共 {job_info['page_count']} 页)")

    doc.close()
    return jobs


def main():
    parser = argparse.ArgumentParser(description="PDF 篇目感知与语义切片工具")
    parser.add_argument("pdf_path", help="输入 PDF 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出工作目录（默认：<PDF所在目录>/<书名>_output）")
    parser.add_argument("--plan", default=None, help="自定义切片计划 JSON 文件路径")
    parser.add_argument("--extract-preview", action="store_true", help="提取前 15 页作为目录排查样例")
    args = parser.parse_args()

    pdf_file = Path(args.pdf_path).resolve()
    if not pdf_file.exists():
        print(f"[-] 错误：文件不存在 {pdf_file}")
        sys.exit(1)

    book_stem = pdf_file.stem
    if args.output:
        work_dir = Path(args.output).resolve()
    else:
        work_dir = pdf_file.parent / f"{book_stem}_output"

    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(work_dir / "parts", exist_ok=True)
    os.makedirs(work_dir / "raw_md", exist_ok=True)
    os.makedirs(work_dir / "raw_json", exist_ok=True)
    os.makedirs(work_dir / "images", exist_ok=True)

    print(f"[*] 处理图书: {pdf_file.name}")
    print(f"[*] 工作目录: {work_dir}")

    doc = fitz.open(str(pdf_file))
    total_pages = len(doc)
    print(f"[*] 全书页数: {total_pages} 页")

    # 1. 提取封面
    cover_path = os.path.join(work_dir, f"{book_stem}_Cover.png")
    extract_cover(doc, cover_path)

    # 2. 检查或读取切片计划
    plan = []
    if args.plan and os.path.exists(args.plan):
        print(f"[*] 加载外部切片计划: {args.plan}")
        with open(args.plan, 'r', encoding='utf-8') as f:
            plan = json.load(f)
    else:
        outline = get_pdf_outline(doc)
        if outline:
            print(f"[*] 检测到 PDF 内置书签大纲 (共 {len(outline)} 条目):")
            for lvl, t, p in outline[:8]:
                print(f"    L{lvl} | P{p:03d} | {t}")
            if len(outline) > 8:
                print(f"    ... 以及后续 {len(outline) - 8} 个条目")
            plan = generate_plan_from_outline(outline, total_pages)
        else:
            print("[!] 未检测到 PDF 书签大纲。")

    # 如果无法自动生成计划，导出前导目录页并提示
    if not plan:
        preview_pdf = work_dir / "preview_toc.pdf"
        p_count = min(15, total_pages)
        preview_doc = fitz.open()
        preview_doc.insert_pdf(doc, from_page=0, to_page=p_count - 1)
        preview_doc.save(str(preview_pdf))
        preview_doc.close()
        print(f"[!] 已导出前 {p_count} 页至: {preview_pdf}")
        print("[!] 请 Agent 或用户检查目录页，生成 slice_plan.json 后重新运行: --plan slice_plan.json")
        doc.close()
        sys.exit(2)

    # 写入切片计划
    plan_path = os.path.join(work_dir, "slice_plan.json")
    with open(plan_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"[*] 切片计划已保存: {plan_path} (共 {len(plan)} 篇目)")

    # 执行物理切片
    print("[*] 开始按篇目物理切分 PDF...")
    jobs = slice_pdf(str(pdf_file), plan, str(work_dir))

    jobs_manifest = {
        "book_title": book_stem,
        "pdf_source": str(pdf_file),
        "total_pages": total_pages,
        "cover_image": cover_path,
        "jobs": jobs
    }
    jobs_path = os.path.join(work_dir, "somark_jobs.json")
    with open(jobs_path, 'w', encoding='utf-8') as f:
        json.dump(jobs_manifest, f, ensure_ascii=False, indent=2)
    print(f"[*] SoMark 任务清单已生成: {jobs_path}")

    doc.close()
    print(f"\n[SUCCESS] 篇目切片规划完成！待处理切片数: {len(jobs)}")


if __name__ == "__main__":
    main()
