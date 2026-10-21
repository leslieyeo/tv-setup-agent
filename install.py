#!/usr/bin/env python3
"""Project-scoped, dependency-free installation for local agents."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
FILES = ["tvsetup.py", "skills", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "plugin.json"]


def install(project, agent):
    project = Path(project).resolve()
    if not project.is_dir():
        raise ValueError("Project directory must already exist")
    state = project / ".tvsetup"
    if state.is_symlink():
        raise ValueError("Refusing symlink .tvsetup directory")
    state.mkdir(mode=0o700, exist_ok=True)
    target = state / "toolkit"
    if target.is_symlink():
        raise ValueError("Refusing a symlink toolkit directory")
    manifest = json.loads((ROOT / "package-manifest.json").read_text())
    for name, sha in manifest["files"].items():
        path = ROOT / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("Package manifest mismatch: " + name)
    desired_links = []
    if agent in ("codex", "both"):
        desired_links.append(project / ".agents/skills/tv-setup")
    if agent in ("claude-code", "both"):
        desired_links.append(project / ".claude/skills/tv-setup")
    skill_target = target / "skills/tv-setup"
    entry = state / "START_HERE.md"
    text = "# TV Setup Agent\n\nRead `toolkit/skills/tv-setup/SKILL.md`, then run `python3 toolkit/tvsetup.py --help` from this directory.\n\nInstallation does not grant permission to reset/flash routers, extract arbitrary credentials, or publish data.\n"
    if entry.exists() and entry.read_text() != text:
        raise ValueError("Existing START_HERE.md preserved")
    # Detect collisions before copying anything or changing existing agent configuration.
    for link in desired_links:
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve() != skill_target:
                raise ValueError("Existing skill preserved; choose another project: " + str(link))
    if target.exists():
        installed = target / "installation.json"
        if not installed.is_file() or json.loads(installed.read_text()).get("package_id") != manifest["package_id"]:
            raise ValueError("An existing toolkit was preserved; remove or migrate it explicitly before upgrading")
        for name, sha in manifest["files"].items():
            if Path(name).parts[0] not in FILES:
                continue
            file = target / name
            if not file.is_file() or file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                raise ValueError("Installed toolkit has local changes; preserved without overwrite: " + name)
    else:
        with tempfile.TemporaryDirectory(prefix=".install-", dir=state) as temp:
            stage = Path(temp) / "toolkit"
            stage.mkdir(mode=0o700)
            for name in FILES:
                src = ROOT / name
                if src.is_dir():
                    shutil.copytree(src, stage / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    shutil.copy2(src, stage / name)
            (stage / "installation.json").write_text(json.dumps({"owner": "tv-setup-agent", "package_id": manifest["package_id"]}))
            stage.rename(target)
    for link in desired_links:
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(os.path.relpath(skill_target, link.parent), target_is_directory=True)
    entry.write_text(text)
    return {"installed": True, "project": str(project), "toolkit": str(target), "agent": agent,
            "links": [str(x) for x in desired_links], "skill": str(skill_target / "SKILL.md"),
            "next": "Ask the local Agent to use tv-setup; if this session has not discovered it, explicitly read the skill path above",
            "device_changes": False}


def main():
    p = argparse.ArgumentParser(description="Install TV Setup Agent into one project; no global settings or devices changed")
    p.add_argument("--agent", choices=["codex", "claude-code", "both", "generic"], default="both")
    p.add_argument("--project", type=Path, default=Path.cwd())
    a = p.parse_args()
    try:
        print(json.dumps(install(a.project, a.agent), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        p.exit(2, "Install stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
