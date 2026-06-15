"""
Two-stage skill loader — mirrors how the agent loop in CLAUDE.md works.

Stage 1 (cheap): list_skills() scans skills/*/SKILL.md and reads ONLY the
  YAML frontmatter to extract {name, description}. Result is module-level
  cached because SKILL.md files don't change per request.

Stage 2 (on-demand): read_skill(name) loads the FULL SKILL.md into a string
  only after the router has committed to a skill. Keeps the routing LLM call
  small — it never sees instructions it won't use.

Frontmatter contract (standardised so matching is reliable):
    name:           short identifier, matches the directory name
    description:    one sentence used by the router for skill selection
    triggers:       list of example phrases (informational; router uses description)
    tools_required: list of tool names the skill needs
    outputs:        what the skill produces
"""

from __future__ import annotations

from pathlib import Path

_SKILLS_DIR = Path(__file__).parent

# Module-level manifest cache.  Call list_skills(invalidate=True) to reset.
_MANIFEST_CACHE: list[dict] | None = None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract simple YAML frontmatter delimited by --- lines.

    Returns (frontmatter_dict, body_text).
    Only scalar key: value pairs are parsed; list values stay as raw strings.
    Uses str.partition so a colon inside the value doesn't split incorrectly.
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()

    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"')

    return fm, body


def list_skills(*, invalidate: bool = False) -> list[dict]:
    """Return [{name, description}, ...] for every skill that has a SKILL.md.

    Reads only frontmatter — the body of each SKILL.md is never loaded here.
    Cached after the first call; pass invalidate=True to force a re-scan.
    """
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None and not invalidate:
        return _MANIFEST_CACHE

    manifest: list[dict] = []
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        fm, _ = _parse_frontmatter(skill_md.read_text())
        name = fm.get("name", "")
        description = fm.get("description", "")
        if name and description:
            manifest.append({"name": name, "description": description})

    _MANIFEST_CACHE = manifest
    return manifest


def read_skill(name: str) -> str:
    """Return the full contents of skills/<name>/SKILL.md.

    Always reads from disk so updated skill instructions are picked up without
    restarting the process.  Only the manifest (list_skills) is cached.

    Raises FileNotFoundError if no such skill directory exists.
    """
    skill_md = _SKILLS_DIR / name / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"No skill named '{name}'. Expected file at: {skill_md}"
        )
    return skill_md.read_text()
