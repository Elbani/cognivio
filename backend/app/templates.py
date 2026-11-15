"""Scaffold content for each memory "shape". These give agents and humans a
consistent, predictable structure so memories understand each other."""

from __future__ import annotations

from app.models.enums import MemoryType

MEMORY_TEMPLATES: dict[str, str] = {
    MemoryType.map.value: (
        "# Project Map\n\n"
        "> The entry point. An agent reads this first to orient itself.\n\n"
        "## What this team owns\n\n- \n\n"
        "## Key systems\n\n- [[How It Works]]\n\n"
        "## Start here\n\n"
        "- Something broke? -> the relevant [[Incident]]\n"
        "- Need to do a task? -> the relevant [[Guide]]\n"
        "- Why is it built this way? -> the relevant [[Decision]]\n\n"
        "## People & ownership\n\n- \n"
    ),
    MemoryType.architecture.value: (
        "# How It Works: <name>\n\n"
        "## Purpose\n\nWhat this system does and why it exists.\n\n"
        "## Components\n\n- \n\n"
        "## Data flow\n\n1. \n\n"
        "## Dependencies\n\n- \n\n"
        "## Gotchas\n\nNon-obvious behavior that surprises newcomers.\n\n- \n\n"
        "## Related\n\n- [[ ]]\n"
    ),
    MemoryType.playbook.value: (
        "# Guide: <task>\n\n"
        "## When to use this\n\nThe situation this guide addresses.\n\n"
        "## The first move\n\nThe single most important thing to do (or NOT do) first.\n\n"
        "## Steps\n\n1. \n2. \n3. \n\n"
        "## Verification\n\nHow you know it worked.\n\n- \n\n"
        "## Escalation\n\nWho to pull in if this doesn't resolve it.\n\n- \n"
    ),
    MemoryType.incident.value: (
        "# Incident: <short title>\n\n"
        "- **Date:** \n- **Severity:** \n- **Owner:** \n\n"
        "## Symptoms\n\nWhat broke and how it showed up.\n\n"
        "## Root cause\n\n\n\n"
        "## Resolution\n\nWhat actually fixed it.\n\n"
        "## Prevention\n\nWhat we changed so it can't recur. -> capture it as a [[Lesson]]\n"
    ),
    MemoryType.decision.value: (
        "# Decision: <title>\n\n"
        "- **Date:** \n- **Status:** proposed | accepted | superseded\n- **Deciders:** \n\n"
        "## Context\n\nThe forces at play and the problem being solved.\n\n"
        "## Decision\n\nWhat we decided to do.\n\n"
        "## Alternatives considered\n\n- \n\n"
        "## Consequences\n\nTrade-offs we accepted.\n\n- \n"
    ),
    MemoryType.lesson.value: (
        "# Lesson: <one-line takeaway>\n\n"
        "## What happened\n\nThe situation that taught us this.\n\n"
        "## The rule going forward\n\nThe durable principle to apply.\n\n"
        "## When it applies\n\nThe trigger that should bring this to mind.\n\n"
        "## Source\n\n- [[ ]]\n"
    ),
    MemoryType.note.value: "",
}


def template_for(memory_type: str) -> str:
    return MEMORY_TEMPLATES.get(memory_type, "")
