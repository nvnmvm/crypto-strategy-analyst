from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_openclaw_skill_frontmatter_and_basedir():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert metadata["name"] == "crypto-strategy-analyst"
    assert isinstance(metadata["description"], str)
    assert "{baseDir}" in body
    assert metadata["metadata"]["openclaw"]["requires"]["bins"] == ["python3"]


def test_git_install_root_contains_skill_file():
    assert (ROOT / "SKILL.md").is_file()
    assert (ROOT / "pyproject.toml").is_file()


def test_release_version_metadata_is_synchronized():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert version == "0.1.2"
    assert project["project"]["version"] == version
    assert f"@v{version}" in (ROOT / "README.md").read_text(encoding="utf-8")
