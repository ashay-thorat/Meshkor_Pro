"""Build data/manifest.csv: one row per file in data/raw.

Run from the infusion-audit folder:
    python build_manifest.py

Fill the source_url column by hand after the first run.
Re-runs keep any source_url and notes you already typed.
"""
import csv
import hashlib
from datetime import datetime
from pathlib import Path

RAW = Path("data/raw")
MANIFEST = Path("data/manifest.csv")
FIELDS = ["source", "subfolder", "file_name", "size_bytes",
          "modified", "sha256", "source_url", "notes"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_existing() -> dict:
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        return {(r["source"], r["subfolder"], r["file_name"]): r
                for r in csv.DictReader(f)}


def main() -> None:
    old = load_existing()
    rows = []
    for path in sorted(RAW.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(RAW)
        source = rel.parts[0]
        subfolder = str(rel.parent.relative_to(source)) if len(rel.parts) > 1 else ""
        key = (source, subfolder, path.name)
        prev = old.get(key, {})
        size = path.stat().st_size
        notes = prev.get("notes", "")
        if size == 0 and "EMPTY" not in notes:
            notes = (notes + " EMPTY FILE").strip()
        rows.append({
            "source": source,
            "subfolder": subfolder,
            "file_name": path.name,
            "size_bytes": size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "sha256": sha256(path),
            "source_url": prev.get("source_url", ""),
            "notes": notes,
        })
        print(f"{source}/{subfolder}/{path.name}  {size:,} bytes")

    # Keep manual rows (e.g. skipped hospitals) that have no file.
    seen = {(r["source"], r["subfolder"], r["file_name"]) for r in rows}
    rows += [r for k, r in old.items() if k not in seen and r.get("notes")]

    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {MANIFEST}")


if __name__ == "__main__":
    main()
