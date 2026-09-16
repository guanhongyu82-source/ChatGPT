#!/usr/bin/env python3
"""Production source-ingestion path for archived Sol Cabinet task materials.

Consumes the verified 00_原稿 manifest, dispatches independent source extraction
in one ready-set, joins traceable records into an evidence pack, and never mutates
the archived sources. Unsupported formats are preserved as unread rather than
guessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import inspect_office


TEXT_SUFFIXES = {".txt", ".md"}
OFFICE_SUFFIXES = {".docx", ".xlsx"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _source_id(index: int, digest: str) -> str:
    return f"source-{index:03d}-{digest[:12]}"


def _load_units(task_dir: Path, manifest_path: Path) -> list[dict]:
    task_root = Path(task_dir).resolve()
    manifest_path = Path(manifest_path).resolve()
    if not task_root.is_dir() or not manifest_path.is_file():
        raise ValueError("task directory and archive manifest must exist")
    if not manifest_path.is_relative_to(task_root):
        raise ValueError("archive manifest must be inside the task directory")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("archive_state") != "PASS":
        raise ValueError("archive manifest is not PASS")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("archive manifest has no source files")

    units = []
    for index, item in enumerate(files, 1):
        if not isinstance(item, dict):
            raise ValueError("invalid archive manifest entry")
        relative = item.get("archived_relative_path")
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("archived_relative_path required")
        path = (task_root / relative).resolve()
        if not path.is_relative_to(task_root) or not path.is_file():
            raise ValueError("archived source escapes task directory or is missing")
        digest = sha256_file(path)
        expected = item.get("archived_sha256") or item.get("source_sha256")
        if not isinstance(expected, str) or digest != expected:
            raise ValueError("archived source hash does not match manifest")
        if item.get("byte_identical") is not True or item.get("source_unmodified") is not True:
            raise ValueError("archive manifest does not prove source preservation")
        units.append(
            {
                "order": index,
                "source_id": _source_id(index, digest),
                "source_role": item.get("source_role"),
                "source_name": item.get("source_name") or path.name,
                "archived_relative_path": relative,
                "path": path,
                "source_sha256": digest,
                "source_type": path.suffix.lower() or "no-extension",
            }
        )
    return units


def extract_source(unit: dict) -> dict:
    path = Path(unit["path"])
    digest = sha256_file(path)
    if digest != unit["source_sha256"]:
        raise ValueError("archived source changed before extraction")

    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        records = [
            {"locator": f"text:line[{index}]", "text": line.strip()}
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if line.strip()
        ]
        locator_scheme = "line"
        unread = []
    elif suffix in OFFICE_SUFFIXES:
        inspected = inspect_office.inspect(path)
        if inspected.get("parse_status") != "PASS" or inspected.get("source_sha256") != digest:
            raise ValueError("Office extraction did not verify the archived source")
        records = [
            {"locator": item["locator"], "text": item["text"]}
            for item in inspected.get("records", [])
            if isinstance(item, dict) and item.get("text")
        ]
        locator_scheme = "format-native"
        unread = []
    else:
        records = []
        locator_scheme = "archive-only"
        unread = [
            f'{unit["source_id"]}:unsupported-content-extraction:{suffix or "no-extension"}'
        ]

    if sha256_file(path) != digest:
        raise ValueError("archived source changed during extraction")
    return {
        "order": unit["order"],
        "source_id": unit["source_id"],
        "source_role": unit["source_role"],
        "source_name": unit["source_name"],
        "archived_relative_path": unit["archived_relative_path"],
        "source_sha256": digest,
        "source_type": unit["source_type"],
        "locator_scheme": locator_scheme,
        "records": records,
        "unread": unread,
    }


def join_evidence(extractions: list[dict]) -> dict:
    ordered = sorted(extractions, key=lambda item: item["order"])
    facts = []
    values_by_key: dict[str, list[dict]] = {}
    unread = []
    seen = set()

    for source in ordered:
        unread.extend(source["unread"])
        for record in source["records"]:
            text = str(record["text"]).strip()
            identity = (
                source["source_id"],
                source["source_sha256"],
                record["locator"],
                text,
            )
            if identity in seen:
                continue
            seen.add(identity)
            fact = {
                "source_id": source["source_id"],
                "source_sha256": source["source_sha256"],
                "locator": record["locator"],
                "text": text,
            }
            if "=" in text:
                key, value = (part.strip() for part in text.split("=", 1))
                if key and value:
                    fact["key"] = key
                    fact["value"] = value
                    values_by_key.setdefault(key, []).append(fact)
            facts.append(fact)

    conflicts = []
    for key, items in sorted(values_by_key.items()):
        values = sorted({item["value"] for item in items})
        if len(values) > 1:
            conflicts.append(
                {
                    "key": key,
                    "values": values,
                    "evidence": [
                        {
                            "source_id": item["source_id"],
                            "source_sha256": item["source_sha256"],
                            "locator": item["locator"],
                        }
                        for item in items
                    ],
                }
            )

    return {
        "sources": [
            {
                "source_id": source["source_id"],
                "source_sha256": source["source_sha256"],
                "source_type": source["source_type"],
                "locator_scheme": source["locator_scheme"],
                "archived_relative_path": source["archived_relative_path"],
            }
            for source in ordered
        ],
        "coverage": [
            {
                "source_id": source["source_id"],
                "record_count": len(source["records"]),
                "state": "UNREAD" if source["unread"] else "EXTRACTED",
            }
            for source in ordered
        ],
        "facts": facts,
        "conflicts": conflicts,
        "unread": unread,
    }


def ingest_archive(task_dir: Path, manifest_path: Path, max_workers: int = 4) -> dict:
    units = _load_units(task_dir, manifest_path)
    width = max(1, min(int(max_workers), len(units)))
    if width == 1:
        extractions = [extract_source(unit) for unit in units]
        mode = "serial"
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=width) as pool:
            for unit in units:
                futures[pool.submit(extract_source, unit)] = unit["source_id"]
            extractions = [future.result() for future in as_completed(futures)]
        mode = "parallel"

    evidence_pack = join_evidence(extractions)
    return {
        "state": "PARTIAL" if evidence_pack["unread"] else "PASS",
        "execution_mode": mode,
        "maximum_parallel_width": width,
        "source_count": len(units),
        "evidence_pack": evidence_pack,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()
    try:
        result = ingest_archive(args.task_dir, args.manifest, args.max_workers)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        result = {"state": "BLOCKED", "reason": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
