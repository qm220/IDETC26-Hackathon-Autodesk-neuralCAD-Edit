#!/usr/bin/env python3
"""Export Mongita records for each request, nested to match img/database_schema.svg.

Schema (one sample = one Request):
  Request
    user        -> User
    brep_start  -> Brep (user -> User)
    edits[]     -> Edit
                    user     -> User
                    brep_end -> Brep (user -> User)
                    ratings[] -> Rating (user -> User, ratings dict)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.utils.db import DatabaseManager
from src.utils.process_config import load_config

DEFAULT_CONFIG = REPO_ROOT / "src" / "config" / "edit_192_external.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "mongita_samples.json"

FEATURE_KEYS = ("feature_dino", "feature_clip_visual", "feature_clip_text")

REQUEST_SCHEMA_FIELDS = (
    "user",
    "difficulty",
    "brep_start",
    "start_time",
    "end_time",
    "text",
    "events",
    "frames_dir",
    "filename",
    "request_type",
    "instructions",
    "modality",
    "assembly",
    "parametric",
)
EDIT_SCHEMA_FIELDS = (
    "request",
    "brep_end",
    "user",
    "start_time",
    "end_time",
    "events",
    "frames_dir",
    "filename",
    "token_count",
)
BREP_SCHEMA_FIELDS = (
    "user",
    "orig_path",
    "end_time",
    "step",
    "f3d",
    "png",
    "jpg",
    "stl",
    "smt",
    "feature_dino",
    "feature_clip_visual",
    "feature_clip_text",
)
USER_SCHEMA_FIELDS = ("is_human",)


def json_safe(value: Any) -> Any:
    if hasattr(value, "__str__") and type(value).__name__ in {"ObjectId", "datetime"}:
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def extra_fields(doc: dict, used: set[str]) -> dict:
    skip = used | {"_id"}
    extra = {k: json_safe(v) for k, v in doc.items() if k not in skip}
    return extra


class Exporter:
    def __init__(self, dbm: DatabaseManager, include_features: bool):
        self.dbm = dbm
        self.include_features = include_features
        self._users: dict[str, dict] = {}
        self._breps: dict[str, dict] = {}

    def user(self, user_id: str | None) -> dict | None:
        if not user_id:
            return None
        if user_id not in self._users:
            doc = self.dbm.users.find_one({"_id": user_id}) or {"_id": user_id}
            out = {"id": doc.get("_id", user_id)}
            for field in USER_SCHEMA_FIELDS:
                out[field] = json_safe(doc.get(field))
            extra = extra_fields(doc, set(USER_SCHEMA_FIELDS))
            if extra:
                out["extra"] = extra
            self._users[user_id] = out
        return self._users[user_id]

    def brep(self, brep_id: str | None) -> dict | None:
        if not brep_id:
            return None
        if brep_id not in self._breps:
            doc = self.dbm.breps.find_one({"_id": brep_id})
            if not doc:
                self._breps[brep_id] = {"id": brep_id, "missing": True}
                return self._breps[brep_id]
            out = {"id": doc["_id"]}
            out["user"] = self.user(doc.get("user"))
            out["orig_path"] = json_safe(doc.get("orig_path", doc.get("orig-path")))
            for field in ("end_time", "step", "f3d", "png", "jpg", "stl", "smt"):
                out[field] = json_safe(doc.get(field))
            for field in FEATURE_KEYS:
                vec = doc.get(field)
                if vec is None:
                    out[field] = None
                elif self.include_features:
                    out[field] = json_safe(vec)
                else:
                    out[field] = {
                        "omitted": True,
                        "length": len(vec) if hasattr(vec, "__len__") else None,
                    }
            used = set(BREP_SCHEMA_FIELDS) | {"orig-path", "orig_path"}
            extra = extra_fields(doc, used)
            if extra:
                out["extra"] = extra
            self._breps[brep_id] = out
        return self._breps[brep_id]

    def rating(self, doc: dict) -> dict:
        reserved = {"user", "edit", "_id"}
        ratings_dict = {k: json_safe(v) for k, v in doc.items() if k not in reserved}
        return {
            "id": str(doc.get("_id")) if doc.get("_id") is not None else None,
            "user": self.user(doc.get("user")),
            "edit": doc.get("edit"),
            "ratings": ratings_dict,
        }

    def edit(self, doc: dict) -> dict:
        out = {"id": doc["_id"]}
        out["request"] = doc.get("request")
        out["brep_end"] = self.brep(doc.get("brep_end"))
        out["user"] = self.user(doc.get("user"))
        out["start_time"] = json_safe(doc.get("start_time"))
        out["end_time"] = json_safe(doc.get("end_time"))
        out["events"] = json_safe(doc.get("events") or [])
        out["frames_dir"] = json_safe(doc.get("frames_dir"))
        out["filename"] = json_safe(doc.get("filename"))
        out["token_count"] = json_safe(doc.get("token_count", doc.get("token_counts")))
        rating_docs = list(self.dbm.ratings.find({"edit": doc["_id"]}))
        out["ratings"] = [self.rating(r) for r in rating_docs]
        used = set(EDIT_SCHEMA_FIELDS) | {"token_counts"}
        extra = extra_fields(doc, used)
        if extra:
            out["extra"] = extra
        return out

    def request(self, doc: dict) -> dict:
        out = {"id": doc["_id"]}
        out["user"] = self.user(doc.get("user"))
        out["difficulty"] = json_safe(doc.get("difficulty"))
        out["brep_start"] = self.brep(doc.get("brep_start"))
        out["start_time"] = json_safe(doc.get("start_time"))
        out["end_time"] = json_safe(doc.get("end_time"))
        out["text"] = json_safe(doc.get("text") or "")
        out["events"] = json_safe(doc.get("events") or [])
        out["frames_dir"] = json_safe(doc.get("frames_dir"))
        out["filename"] = json_safe(doc.get("filename"))
        out["request_type"] = json_safe(doc.get("request_type"))
        out["instructions"] = json_safe(doc.get("instructions"))
        out["modality"] = json_safe(doc.get("modality"))
        out["assembly"] = json_safe(doc.get("assembly"))
        out["parametric"] = json_safe(doc.get("parametric"))
        edits = list(self.dbm.edits.find({"request": doc["_id"]}))
        edits.sort(key=lambda e: str(e.get("_id")))
        out["edits"] = [self.edit(e) for e in edits]
        extra = extra_fields(doc, set(REQUEST_SCHEMA_FIELDS))
        if extra:
            out["extra"] = extra
        return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump nested Mongita records for requests (schema-aligned JSON)."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Export only the first N requests (sorted by id). Use 1 to test.",
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="Export a single request by id.",
    )
    parser.add_argument(
        "--include-features",
        action="store_true",
        help="Include full DINO/CLIP vectors (very large).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    dbm = DatabaseManager(config)
    exporter = Exporter(dbm, include_features=args.include_features)

    if args.request_id:
        query = {"_id": args.request_id}
    else:
        query = {}

    requests = list(dbm.requests.find(query))
    requests.sort(key=lambda r: str(r["_id"]))
    if args.limit is not None:
        requests = requests[: args.limit]

    samples = [exporter.request(r) for r in requests]
    payload = {
        "schema": "img/database_schema.svg",
        "storage_dir": config["storage_dir"]["path"],
        "include_features": args.include_features,
        "count": len(samples),
        "samples": samples,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    n_edits = sum(len(s["edits"]) for s in samples)
    n_ratings = sum(len(e["ratings"]) for s in samples for e in s["edits"])
    print(f"Wrote {len(samples)} request(s), {n_edits} edit(s), {n_ratings} rating(s)")
    print(f"Output: {output_path}")
    dbm.close_connection()


if __name__ == "__main__":
    main()
