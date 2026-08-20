#!/usr/bin/env python3
"""Copy submission artifacts from a harness output dir.

For each sample, copies settings.json, STEP, STL, and multi-view images into:

    submission_folder/submission outputs/<edit_id>/brep_end/<timestamp>/

Does not copy planning/iteration logs or temp_script.py.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

KEEP_NAMES = {"settings.json"}
KEEP_SUFFIXES = {".step", ".stp", ".stl", ".png", ".jpg", ".jpeg"}


def latest_brep_end(sample_dir: Path) -> Path | None:
    brep_end = sample_dir / "brep_end"
    if not brep_end.is_dir():
        return None
    folders = sorted(p for p in brep_end.iterdir() if p.is_dir())
    return folders[-1] if folders else None


def should_copy(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name in KEEP_NAMES:
        return True
    return path.suffix.lower() in KEEP_SUFFIXES


def copy_sample(src_final: Path, dest_root: Path) -> tuple[int, list[str]]:
    dest = dest_root / src_final.parents[1].name / "brep_end" / src_final.name
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    missing = []
    copied_kinds = {"settings.json": False, "step": False, "stl": False, "images": 0}
    for src in src_final.iterdir():
        if not should_copy(src):
            continue
        shutil.copy2(src, dest / src.name)
        n += 1
        name = src.name.lower()
        suf = src.suffix.lower()
        if name == "settings.json":
            copied_kinds["settings.json"] = True
        elif suf in {".step", ".stp"}:
            copied_kinds["step"] = True
        elif suf == ".stl":
            copied_kinds["stl"] = True
        elif suf in {".png", ".jpg", ".jpeg"}:
            copied_kinds["images"] += 1
    if not copied_kinds["settings.json"]:
        missing.append("settings.json")
    if not copied_kinds["step"]:
        missing.append("step")
    if not copied_kinds["stl"]:
        missing.append("stl")
    if copied_kinds["images"] == 0:
        missing.append("images")
    return n, missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", help="Harness output directory")
    parser.add_argument(
        "--dest",
        default="submission_folder/submission outputs",
        help="Submission destination (default: submission_folder/submission outputs)",
    )
    args = parser.parse_args()

    src_root = Path(args.output_dir).resolve()
    dest_root = Path(args.dest)
    if not dest_root.is_absolute():
        dest_root = Path.cwd() / dest_root
    dest_root.mkdir(parents=True, exist_ok=True)

    samples = sorted(p for p in src_root.iterdir() if p.is_dir())
    n_ok = 0
    n_partial = 0
    n_skip = 0
    n_files = 0
    for sample in samples:
        src_final = latest_brep_end(sample)
        if src_final is None:
            n_skip += 1
            continue
        copied, missing = copy_sample(src_final, dest_root)
        n_files += copied
        if missing:
            n_partial += 1
            print(f"PARTIAL {sample.name}: copied={copied} missing={missing}")
        else:
            n_ok += 1
    print(
        f"Copied {n_files} files from {src_root} -> {dest_root} "
        f"(complete={n_ok} partial={n_partial} skipped={n_skip})"
    )


if __name__ == "__main__":
    main()
