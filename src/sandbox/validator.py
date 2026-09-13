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

    Generated skills may use the narrow public Skill contract from ``core`` and
    pure computation helpers. They must receive host capabilities through
    reviewed dependency injection. Direct process, network, filesystem, database,
    project-internal, dynamic-import, or kernel-control imports are rejected.

    This gate is intentionally defense-in-depth; SandboxRunner is still process
    isolation rather than a hardened VM, so passing this validator never grants a
    candidate automatic runtime promotion.
    """

    FORBIDDEN_MODULES = {
        # Host/process/network/filesystem/database escape hatches.
        "builtins",
        "bridges",
        "ctypes",
        "dbm",
        "ftplib",
        "glob",
        "http",
        "importlib",
        "io",
        "marshal",
        "mmap",
        "multiprocessing",
        "os",
        "pathlib",
        "pickle",
        "requests",
        "shelve",
        "shutil",
        "smtplib",
        "socket",
        "sqlite3",
        "subprocess",
        "sys",
        "tempfile",
        "urllib",
        "webbrowser",
        "winreg",
        # NEXA internals that generated plugins must not reach directly.
        "git_router",
        "git_skill",
        "language",
        "memory",
        "nexa",
        "runtime",
        "sandbox",
        "skills",
        "teacher",
        "training",
        "workspace",
    }
    ALLOWED_CORE_SYMBOLS = {
        "ExecutionResult",
        "OperationSpec",
        "RiskTier",
        "SkillMatch",
        "SkillMetadata",
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
    FORBIDDEN_NAMES = {
        "__builtins__",
        "__loader__",
        "__spec__",
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
            if root == "core":
                self._add(
                    node,
                    "unsafe_core_import",
                    "bare 'import core' is blocked; import only approved Skill contract symbols",
                )
            elif root in self.FORBIDDEN_MODULES:
                self._add(node, "forbidden_import", f"direct import blocked: {root}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if root == "core":
            if node.level != 0 or node.module != "core":
                self._add(node, "unsafe_core_import", "only 'from core import ...' is allowed")
            for alias in node.names:
                if alias.name == "*" or alias.name not in self.ALLOWED_CORE_SYMBOLS:
                    self._add(
                        node,
                        "unsafe_core_symbol",
                        f"generated skill cannot import core symbol: {alias.name}",
                    )
        elif root in self.FORBIDDEN_MODULES:
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

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.FORBIDDEN_NAMES:
            self._add(node, "forbidden_name", f"name access blocked: {node.id}")
        self.generic_visit(node)

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self._findings.append(ValidationFinding(getattr(node, "lineno", 0), code, message))
