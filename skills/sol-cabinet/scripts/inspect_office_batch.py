#!/usr/bin/env python3
"""Batch read-only DOCX/XLSX inspection for independent Office artifacts.

Runs the existing inspect_office.inspect implementation concurrently across
independent files. It does not change inspection semantics, mutate inputs,
render Office files, access the network, or convert formats.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

from inspect_office import inspect


EXPECTED_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    ET.ParseError,
    zipfile.BadZipFile,
    RuntimeError,
)


def inspect_many(paths, stale=(), max_workers=None):
    items = [Path(path) for path in paths]
    if not items:
        raise ValueError("at least one Office file is required")
    if max_workers is not None and (isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1):
        raise ValueError("max_workers must be a positive integer")

    runtime_width = max(1, os.cpu_count() or 1)
    workers = min(len(items), max_workers if max_workers is not None else runtime_width)
    results = [None] * len(items)

    def run_one(index, path):
        started = time.perf_counter()
        try:
            result = inspect(path, stale)
        except EXPECTED_ERRORS:
            result = {
                "parse_status": "BLOCKED",
                "overall_verdict": "NOT_ASSESSED",
                "read_only": True,
                "reason": "输入不可读、损坏、不支持或超限；未退回二进制猜读",
            }
        return {
            "index": index,
            "path": str(path),
            "elapsed_seconds": time.perf_counter() - started,
            "result": result,
        }

    batch_started = time.perf_counter()
    if workers == 1:
        for index, path in enumerate(items):
            results[index] = run_one(index, path)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sol-office-inspect") as executor:
            futures = {executor.submit(run_one, index, path): index for index, path in enumerate(items)}
            for future in as_completed(futures):
                item = future.result()
                results[item["index"]] = item

    wall = time.perf_counter() - batch_started
    serial_sum = sum(item["elapsed_seconds"] for item in results)
    overall = "PASS" if all(item["result"].get("parse_status") == "PASS" for item in results) else "BLOCKED"
    return {
        "parse_status": overall,
        "overall_verdict": "NOT_ASSESSED",
        "read_only": True,
        "file_count": len(items),
        "maximum_parallel_width": workers,
        "wall_clock_seconds": wall,
        "serial_work_seconds": serial_sum,
        "timing_basis": "single-process perf_counter; observational only, not a quality gate",
        "items": results,
        "limitation": "批量并行只缩短独立机械检查路径，不替代事实、内容、视觉验收或最终 Delivery Gate",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--stale", action="append", default=[])
    parser.add_argument("--max-workers", type=int)
    args = parser.parse_args()
    try:
        result = inspect_many(args.paths, args.stale, args.max_workers)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"parse_status": "BLOCKED", "reason": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["parse_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
