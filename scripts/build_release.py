#!/usr/bin/env python3
"""Allowlisted archive export, never recursively package a user's workspace."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["README.md", "CONTRIBUTING.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "plugin.json", "install.py", "tvsetup.py", ".gitignore", ".gitattributes", ".github", "skills", "tests", "scripts", "validation.json"]


def source_files():
    files = []
    for name in INCLUDE:
        path = ROOT / name
        if not path.exists():
            if name == "validation.json":
                continue
            raise ValueError("Missing release component: " + name)
        for item in ([path] if path.is_file() else path.rglob("*")):
            if item.is_symlink():
                raise ValueError("No symlinks in release sources")
            if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                files.append(item)
    return sorted(files)


def build(destination=None):
    files = source_files()
    manifest = {"schema": 1, "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    manifest["package_id"] = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    path = ROOT / "package-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    if destination:
        destination = Path(destination).resolve()
        if destination.is_relative_to(ROOT):
            raise ValueError("Archive must be written outside the package source")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in files + [path]:
                archive.write(item, "tv-setup-agent/" + str(item.relative_to(ROOT)))
        with zipfile.ZipFile(destination) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError("Archive CRC failure: " + bad)
        return {"archive": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "files": len(files) + 1}
    return {"manifest_ready": True, "files": len(files), "package_id": manifest["package_id"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out")
    print(json.dumps(build(p.parse_args().out), indent=2))
