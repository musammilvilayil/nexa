from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CapabilityValidationFinding:
    line: int
    rule: str
    message: str


@dataclass(frozen=True)
class CapabilityValidationReport:
    valid: bool
    findings: tuple[CapabilityValidationFinding, ...]
    class_name: str | None = None
    operations: tuple[str, ...] = ()


class CapabilityValidator(ast.NodeVisitor):
    """AST validator and safety checker for dynamically generated capabilities."""

    FORBIDDEN_CALLS = {
        "__import__",
        "compile",
        "eval",
        "exec",
    }

    FORBIDDEN_MODULES = {
        "ctypes",
        "socket",
        "requests",
        "urllib",
        "multiprocessing",
        "winreg",
        "pty",
        "fcntl",
    }

    FORBIDDEN_ATTRIBUTES = {
        "popen",
        "system",
    }

    ALLOWED_CORE_SYMBOLS = {
        "ExecutionResult",
        "OperationSpec",
        "RiskTier",
        "Skill",
        "SkillMatch",
        "SkillMetadata",
    }

    def __init__(self) -> None:
        self._findings: list[CapabilityValidationFinding] = []
        self._classes: list[str] = []
        self._has_metadata: bool = False
        self._has_match: bool = False
        self._has_validate: bool = False
        self._has_execute: bool = False

    def validate(self, source: str) -> CapabilityValidationReport:
        self._findings = []
        self._classes = []
        self._has_metadata = False
        self._has_match = False
        self._has_validate = False
        self._has_execute = False

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return CapabilityValidationReport(
                valid=False,
                findings=(
                    CapabilityValidationFinding(
                        exc.lineno or 0, "syntax_error", str(exc.msg)
                    ),
                ),
            )

        self.visit(tree)

        # Ensure at least one class defines the Skill interface methods
        if not self._classes:
            self._findings.append(
                CapabilityValidationFinding(1, "missing_class", "No class definition found")
            )
        elif not (self._has_match and self._has_validate and self._has_execute):
            self._findings.append(
                CapabilityValidationFinding(
                    1,
                    "incomplete_skill_contract",
                    "Skill class must implement match, validate, and execute methods",
                )
            )

        valid = len(self._findings) == 0
        main_class = self._classes[0] if self._classes else None
        return CapabilityValidationReport(
            valid=valid,
            findings=tuple(self._findings),
            class_name=main_class,
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in self.FORBIDDEN_MODULES:
                self._findings.append(
                    CapabilityValidationFinding(
                        node.lineno,
                        "forbidden_import",
                        f"Importing module '{root}' is forbidden in dynamic skills",
                    )
                )
            elif root == "core":
                self._findings.append(
                    CapabilityValidationFinding(
                        node.lineno,
                        "unsafe_core_import",
                        "Bare 'import core' not allowed; use 'from core import ...'",
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if root in self.FORBIDDEN_MODULES:
            self._findings.append(
                CapabilityValidationFinding(
                    node.lineno,
                    "forbidden_import",
                    f"Importing from '{root}' is forbidden in dynamic skills",
                )
            )
        elif root == "core":
            for alias in node.names:
                if alias.name != "*" and alias.name not in self.ALLOWED_CORE_SYMBOLS:
                    self._findings.append(
                        CapabilityValidationFinding(
                            node.lineno,
                            "unsafe_core_symbol",
                            f"Core symbol '{alias.name}' is not an approved skill symbol",
                        )
                    )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in self.FORBIDDEN_CALLS:
                self._findings.append(
                    CapabilityValidationFinding(
                        node.lineno,
                        "forbidden_call",
                        f"Calling function '{node.func.id}' is forbidden",
                    )
                )
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in self.FORBIDDEN_ATTRIBUTES:
                self._findings.append(
                    CapabilityValidationFinding(
                        node.lineno,
                        "forbidden_attribute",
                        f"Accessing attribute '{node.func.attr}' is forbidden",
                    )
                )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._classes.append(node.name)
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name == "match":
                    self._has_match = True
                elif item.name == "validate":
                    self._has_validate = True
                elif item.name == "execute":
                    self._has_execute = True
                elif item.name == "__init__":
                    self._has_metadata = True
        self.generic_visit(node)
