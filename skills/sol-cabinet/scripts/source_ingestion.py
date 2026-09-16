#!/usr/bin/env python3
"""Production source-ingestion path for archived Sol Cabinet task materials.

Consumes the canonical verified ``00_原稿/原稿清单.json``, dispatches independent
source extraction in one ready-set, joins traceable records into an evidence pack,
and never mutates archived sources. Unsupported or actually unverified source
portions are preserved as unread instead of being silently treated as covered.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import inspect_office


ARCHIVE_DIR_NAME = "00_原稿"
MANIFEST_NAME = "原稿清单.json"
ROLE_RE = re.compile(r"^[^/\\\x00-\x1f]{1,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECORD_KEYS = {
    "source_role",
    "source_name",
    "archived_relative_path",
    "size_bytes",
    "source_sha256",
    "archived_sha256",
    "byte_identical",
    "source_unmodified",
    "status",
}
TEXT_SUFFIXES = {".txt", ".md"}
OFFICE_SUFFIXES = {".docx", ".xlsx"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _source_id(index: int, digest: str) -> str:
    return f"source-{index:03d}-{digest[:12]}"


def _validate_basename(name: object) -> str:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("source filename is invalid")
    if any(ord(char) < 32 for char in name) or len(name.encode("utf-8")) > 180:
        raise ValueError("source filename is invalid")
    return name


def _load_units(task_dir: Path, manifest_path: Path) -> list[dict]:
    task_root = Path(task_dir).resolve()
    supplied_manifest = Path(manifest_path)
    canonical_archive = task_root / ARCHIVE_DIR_NAME
    canonical_manifest = canonical_archive / MANIFEST_NAME

    if not task_root.is_dir() or not canonical_archive.is_dir():
        raise ValueError("task directory and canonical archive directory must exist")
    if canonical_archive.is_symlink() or supplied_manifest.is_symlink():
        raise ValueError("canonical archive directory and manifest must not be symlinks")
    try:
        resolved_manifest = supplied_manifest.resolve(strict=True)
        expected_manifest = canonical_manifest.resolve(strict=True)
    except OSError as exc:
        raise ValueError("canonical archive manifest must exist") from exc
    if resolved_manifest != expected_manifest:
        raise ValueError("manifest must be the canonical 00_原稿/原稿清单.json")
    if not canonical_manifest.is_file():
        raise ValueError("canonical archive manifest must be a regular file")

    manifest = json.loads(canonical_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "archive_state", "files"}:
        raise ValueError("archive manifest schema is invalid")
    if manifest["schema_version"] != 1 or manifest["archive_state"] != "PASS":
        raise ValueError("archive manifest state is invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("archive manifest has no source files")

    units = []
    seen_relative_paths = set()
    seen_identities = set()
    for index, item in enumerate(files, 1):
        if not isinstance(item, dict) or set(item) != RECORD_KEYS:
            raise ValueError("archive manifest record schema is invalid")
        role = item.get("source_role")
        source_name = item.get("source_name")
        relative = item.get("archived_relative_path")
        if not isinstance(role, str) or not ROLE_RE.fullmatch(role) or role in {".", ".."}:
            raise ValueError("source_role is invalid")
        source_name = _validate_basename(source_name)
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("archived_relative_path required")

        relative_path = Path(relative)
        expected_name = f"原稿_{role}_{source_name}"
        expected_relative = Path(ARCHIVE_DIR_NAME) / expected_name
        if relative_path.is_absolute() or relative_path != expected_relative:
            raise ValueError("archived source is not a canonical 00_原稿 member")
        identity = (role, source_name, item["source_sha256"])
        if relative in seen_relative_paths or identity in seen_identities:
            raise ValueError("duplicate archive manifest record")
        seen_relative_paths.add(relative)
        seen_identities.add(identity)

        path = canonical_archive / expected_name
        if path.is_symlink() or not path.is_file() or path.parent.resolve() != canonical_archive.resolve():
            raise ValueError("canonical archived source is missing, linked, or escapes 00_原稿")

        size_bytes = item.get("size_bytes")
        if type(size_bytes) is not int or size_bytes < 0:
            raise ValueError("archive manifest size is invalid")
        source_digest = item.get("source_sha256")
        archived_digest = item.get("archived_sha256")
        if not isinstance(source_digest, str) or not SHA256_RE.fullmatch(source_digest):
            raise ValueError("archive manifest source hash is invalid")
        if not isinstance(archived_digest, str) or not SHA256_RE.fullmatch(archived_digest):
            raise ValueError("archive manifest archive hash is invalid")
        if source_digest != archived_digest:
            raise ValueError("source and archived hashes differ")
        if path.stat().st_size != size_bytes:
            raise ValueError("archived source size does not match manifest")
        digest = sha256_file(path)
        if digest != archived_digest:
            raise ValueError("archived source hash does not match manifest")
        if item.get("byte_identical") is not True or item.get("source_unmodified") is not True:
            raise ValueError("archive manifest does not prove source preservation")
        if item.get("status") != "UNMODIFIED_BYTE_COPY":
            raise ValueError("archive manifest entry status is not canonical")

        units.append(
            {
                "order": index,
                "source_id": _source_id(index, digest),
                "source_role": role,
                "source_name": source_name,
                "archived_relative_path": relative,
                "path": path,
                "source_sha256": digest,
                "source_type": path.suffix.lower() or "no-extension",
            }
        )
    return units


def _office_unread(path: Path, inspected: dict, source_id: str) -> list[str]:
    coverage = inspected.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("Office inspector coverage is missing")
    limitations = coverage.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise ValueError("Office inspector limitations are malformed")

    unread: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".docx" and coverage.get("tracked_deletion_groups", 0):
        unread.append(f"{source_id}:docx-tracked-deletions-not-extracted")
    if suffix == ".xlsx":
        sheets = coverage.get("sheets", [])
        if not isinstance(sheets, list):
            raise ValueError("Office inspector sheet coverage is malformed")
        formula_count = sum(
            item.get("formula_count", 0)
            for item in sheets
            if isinstance(item, dict) and type(item.get("formula_count", 0)) is int
        )
        if formula_count:
            unread.append(f"{source_id}:xlsx-formulas-not-recalculated:{formula_count}")

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            if suffix == ".docx":
                unsupported_prefixes = {
                    "word/media/": "docx-images-not-ocr",
                    "word/charts/": "docx-charts-not-extracted",
                    "word/embeddings/": "docx-embedded-objects-not-extracted",
                }
                xml_names = [name for name in names if name.startswith("word/") and name.endswith(".xml")]
                if any(
                    token in package.read(name)
                    for name in xml_names
                    for token in (b"fldSimple", b"instrText", b"fldChar")
                ):
                    unread.append(f"{source_id}:docx-fields-not-evaluated")
            else:
                unsupported_prefixes = {
                    "xl/media/": "xlsx-images-not-inspected",
                    "xl/charts/": "xlsx-charts-not-inspected",
                    "xl/drawings/": "xlsx-drawings-not-inspected",
                    "xl/embeddings/": "xlsx-embedded-objects-not-inspected",
                    "xl/externalLinks/": "xlsx-external-links-not-resolved",
                }
            for prefix, reason in unsupported_prefixes.items():
                if any(name.startswith(prefix) for name in names):
                    unread.append(f"{source_id}:{reason}")

    return list(dict.fromkeys(unread))


def extract_source(unit: dict) -> dict:
    path = Path(unit["path"])
    digest = sha256_file(path)
    if digest != unit["source_sha256"]:
        raise ValueError("archived source changed before extraction")

    suffix = path.suffix.lower()
    inspection_coverage = None
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
        inspection_coverage = inspected.get("coverage")
        unread = _office_unread(path, inspected, unit["source_id"])
        records = [
            {"locator": item["locator"], "text": item["text"]}
            for item in inspected.get("records", [])
            if isinstance(item, dict) and item.get("text")
        ]
        locator_scheme = "format-native"
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
        "inspection_coverage": inspection_coverage,
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

    coverage = []
    for source in ordered:
        if source["unread"]:
            state = "PARTIAL" if source["records"] else "UNREAD"
        else:
            state = "EXTRACTED"
        coverage.append(
            {
                "source_id": source["source_id"],
                "record_count": len(source["records"]),
                "state": state,
                "inspection_coverage": source.get("inspection_coverage"),
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
        "coverage": coverage,
        "facts": facts,
        "conflicts": conflicts,
        "unread": list(dict.fromkeys(unread)),
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
