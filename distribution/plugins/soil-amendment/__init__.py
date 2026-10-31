"""soil-amendment - a whitelabel Hermes plugin.

Registers two tools and bundles a skill:

    soil_amendment  - read an EAL soil certificate of analysis, return a structured
                      amendment program (all arithmetic done here, not by the model)
    soil_test_read  - parse and summarise a certificate of analysis without a program

The engine contains no vendor names: product tables, application ceilings, target
levels and rule wording all come from a profile in profiles/. See the bundled skill.
"""
from __future__ import annotations

from pathlib import Path

from . import schemas, tools


def register(ctx):
    global _CTX
    tools._CTX = ctx

    ctx.register_tool(
        name="soil_amendment",
        toolset="soil",
        schema=schemas.SOIL_AMENDMENT,
        handler=tools.soil_amendment,
    )
    ctx.register_tool(
        name="soil_test_read",
        toolset="soil",
        schema=schemas.SOIL_TEST_READ,
        handler=tools.soil_test_read,
    )

    # Bundle the skill with the plugin. Note this is namespaced and read-only, and is
    # NOT listed in the system prompt's skill index - a separate copy installed under
    # the profile's skills/ directory is what makes it discoverable.
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
