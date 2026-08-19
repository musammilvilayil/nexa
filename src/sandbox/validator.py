from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationFinding:
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class StaticValidationReport:
    safe: bool
    findings: tuple[ValidationFinding, ...]


class StaticValidator(ast.NodeVisitor):
    """Conservative AST gate for teacher-generated plugin code.

    Generated skills must receive capabilities through reviewed dependency
    injection. They cannot import process/network bridges or raw escape hatches.
    """

    FORBIDDEN_MODULES = {
        "bridges",
        "ctypes",
        "ftplib",
        "http",
        "multiprocessing",
        "os",
        "requests",
        "shutil",
        "smtplib",
        "socket",
        "subprocess",
        "urllib",
        "winreg",
    }
    FORBIDDEN_CALL_NAMES = {
        "__import__",
        "compile",
        "eval",
        "exec",
        "open",
    }
    FORBIDDEN_ATTRIBUTES = {
        "popen",
        "remove",
        "rmdir",
        "system",
        "unlink",
    }

    def __init__(self) -> None:
        self._findings: list[ValidationFinding] = []

    def validate(self, source: str) -> StaticValidationReport:
        self._findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return StaticValidationReport(
                False,
                (ValidationFinding(exc.lineno or 0, "syntax_error", exc.msg),),
            )
        self.visit(tree)
        return StaticValidationReport(not self._findings, tuple(self._findings))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in self.FORBIDDEN_MODULES:
                self._add(node, "forbidden_import", f"direct import blocked: {root}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if root in self.FORBIDDEN_MODULES:
            self._add(node, "forbidden_import", f"direct import blocked: {root}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in self.FORBIDDEN_CALL_NAMES:
            self._add(node, "forbidden_call", f"call blocked: {node.func.id}")

        if isinstance(node.func, ast.Attribute) and node.func.attr in self.FORBIDDEN_ATTRIBUTES:
            self._add(node, "forbidden_attribute", f"attribute call blocked: {node.func.attr}")

        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                self._add(node, "shell_true", "subprocess shell=True is forbidden")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self._add(node, "dunder_access", "dunder attribute access is forbidden in generated skills")
        self.generic_visit(node)

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self._findings.append(ValidationFinding(getattr(node, "lineno", 0), code, message))
