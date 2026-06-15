"""
Tests for the two-stage skill loader (skills/skill_loader.py).

These tests run entirely against the on-disk skills/ directory — no mocking,
no network. They verify:
  - list_skills returns valid {name, description} entries for every skill stub
  - read_skill returns the full file content including the frontmatter delimiter
  - the manifest cache is correctly invalidated
  - missing skills raise FileNotFoundError (not a silent empty string)
"""

import pytest

from skills.skill_loader import _parse_frontmatter, list_skills, read_skill


# ── _parse_frontmatter ─────────────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_extracts_name_and_description(self):
        text = "---\nname: my_skill\ndescription: Does something useful\n---\nbody"
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "my_skill"
        assert fm["description"] == "Does something useful"
        assert "body" in body

    def test_description_with_colon_preserved(self):
        text = "---\nname: x\ndescription: Collect goal: amount and date\n---\n"
        fm, _ = _parse_frontmatter(text)
        # partition on first colon only — the rest of the value is kept
        assert "amount and date" in fm["description"]

    def test_no_frontmatter_returns_empty_dict(self):
        text = "# Just a markdown file\nno frontmatter"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert "Just a markdown file" in body

    def test_unclosed_delimiter_returns_empty_dict(self):
        text = "---\nname: broken\n"  # no closing ---
        fm, _ = _parse_frontmatter(text)
        assert fm == {}


# ── list_skills ────────────────────────────────────────────────────────────────

class TestListSkills:
    def test_returns_list_of_dicts(self):
        skills = list_skills(invalidate=True)
        assert isinstance(skills, list)
        assert len(skills) > 0

    def test_every_entry_has_name_and_description(self):
        for skill in list_skills(invalidate=True):
            assert "name" in skill, f"missing 'name' in {skill}"
            assert "description" in skill, f"missing 'description' in {skill}"
            assert skill["name"], "name must not be empty"
            assert skill["description"], "description must not be empty"

    def test_expected_stubs_present(self):
        names = {s["name"] for s in list_skills(invalidate=True)}
        for expected in ("goal_intake", "recommend_framework",
                         "build_budget", "diagnose_overspend"):
            assert expected in names, f"skill '{expected}' not found in manifest"

    def test_cache_returns_same_object(self):
        first = list_skills(invalidate=True)
        second = list_skills()  # should hit cache
        assert first is second

    def test_invalidate_rescans(self):
        a = list_skills(invalidate=True)
        b = list_skills(invalidate=True)
        # After invalidation, a fresh list is returned (different object)
        assert a is not b
        # But the content should be the same
        assert a == b


# ── read_skill ─────────────────────────────────────────────────────────────────

class TestReadSkill:
    def test_returns_full_content(self):
        content = read_skill("goal_intake")
        assert "---" in content           # frontmatter delimiters present
        assert "goal_intake" in content   # name referenced in body

    def test_content_includes_body(self):
        content = read_skill("recommend_framework")
        # Skill body should have some instructions beyond frontmatter
        assert len(content) > 200

    def test_missing_skill_raises(self):
        with pytest.raises(FileNotFoundError):
            read_skill("nonexistent_skill_xyz")

    @pytest.mark.parametrize("skill_name", [
        "goal_intake",
        "recommend_framework",
        "build_budget",
        "diagnose_overspend",
    ])
    def test_all_stubs_readable(self, skill_name):
        content = read_skill(skill_name)
        assert content.startswith("---"), (
            f"skills/{skill_name}/SKILL.md must start with YAML frontmatter (---)"
        )
