"""
Fetch Interlude skill/item names from Hl4p3x/L2JServer_C6_Interlude (GPL datapack)
and write data/skills_en.json and data/items_en.json.

Run from repo root: python scripts/fetch_l2j_reference.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API = "https://api.github.com/repos/Hl4p3x/L2JServer_C6_Interlude/contents/dist/game/data/stats"
RAW = "https://raw.githubusercontent.com/Hl4p3x/L2JServer_C6_Interlude/master/dist/game/data/stats"
USER_AGENT = "L2Bot-reference-fetch/1.0"


def _api_json(path: str) -> list[dict]:
    url = f"{API}/{path}?ref=master"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_xml(rel_path: str) -> bytes:
    url = f"{RAW}/{rel_path}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _parse_skills(xml_bytes: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for skill in root.iter("skill"):
        sid = skill.get("id")
        name = skill.get("name")
        if sid and name:
            out[sid] = name.strip()
    return out


def _parse_items(xml_bytes: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        iid = item.get("id")
        iname = item.get("name")
        if iid and iname:
            out[iid] = iname.strip()
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    skills: dict[str, str] = {}
    items: dict[str, str] = {}

    print("Listing skills/*.xml via GitHub API...")
    for entry in _api_json("skills"):
        if entry.get("type") != "file" or not str(entry["name"]).endswith(".xml"):
            continue
        name = entry["name"]
        print(f"  skills/{name}")
        skills.update(_parse_skills(_fetch_xml(f"skills/{name}")))

    print("Listing items/*.xml via GitHub API...")
    for entry in _api_json("items"):
        if entry.get("type") != "file" or not str(entry["name"]).endswith(".xml"):
            continue
        name = entry["name"]
        print(f"  items/{name}")
        items.update(_parse_items(_fetch_xml(f"items/{name}")))

    (data_dir / "skills_en.json").write_text(
        json.dumps(skills, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (data_dir / "items_en.json").write_text(
        json.dumps(items, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Done: {len(skills)} skills, {len(items)} items -> {data_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
