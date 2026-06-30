from __future__ import annotations

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
