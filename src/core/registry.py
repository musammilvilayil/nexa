from __future__ import annotations

from typing import Any, Mapping

from .contracts import Skill, SkillMatch


class RegistryError(RuntimeError):
    pass


class SkillRegistry:
    """Runtime registry for capability plugins.

    Registration order is stable. Matching remains deterministic when confidence
    scores tie: the first registered matching skill wins.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._order: list[str] = []

    def register(self, skill: Skill) -> None:
        name = skill.metadata.name.strip()
        if not name:
            raise RegistryError("Skill name cannot be empty")
        if name in self._skills:
            raise RegistryError(f"Skill already registered: {name}")
        self._skills[name] = skill
        self._order.append(name)

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise RegistryError(f"Unknown skill: {name}") from exc

    def list_metadata(self):
        return tuple(self._skills[name].metadata for name in self._order)

    def resolve(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        candidates: list[tuple[int, SkillMatch]] = []

        for index, name in enumerate(self._order):
            skill = self._skills[name]
            match = skill.match(text, context)
            if match is None:
                continue
            if match.skill_name != skill.metadata.name:
                raise RegistryError(
                    f"Skill {skill.metadata.name} returned mismatched name {match.skill_name}"
                )
            if not 0.0 <= match.confidence <= 1.0:
                raise RegistryError("Skill match confidence must be between 0 and 1")
            candidates.append((index, match))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[1].confidence, item[0]))
        return candidates[0][1]
