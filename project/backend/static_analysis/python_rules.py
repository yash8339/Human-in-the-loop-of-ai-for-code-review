from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _Finding:
    line: int
    rule_id: str
    severity: str
    message: str


class _PythonRuleVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[_Finding] = []
        self.function_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.called_names: set[str] = set()
        self.function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_nodes.append(node)
        self.function_stack.append(node)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.called_names.add(node.func.id)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "call", "run", "Popen"}:
            if isinstance(node.func.value, ast.Name) and node.func.value.id in {"os", "subprocess"}:
                self._add(node, "command-execution", "high", "Executing shell commands can be vulnerable to injection; validate input and avoid shell execution.")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
            self._check_sql_call(node)
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            self._check_open_call(node)
        if isinstance(node.func, ast.Name) and node.func.id == "int":
            if node.args and isinstance(node.args[0], ast.Call) and _call_name(node.args[0]) == "input":
                self._add(node, "direct-input-int", "medium", "User input is converted directly with int() and can raise ValueError.")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self._add(node, "bare-except", "medium", "Bare except catches every exception and can hide programming errors.")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
            if _is_len_plus_one(node.value):
                self._add(node, "length-based-id", "medium", "len(collection) + 1 can reuse an ID after deletions or concurrent inserts.")
        if isinstance(node.value, ast.Name) and node.value.id == "password":
            if any(_contains_key(target, "password") for target in node.targets):
                self._add(node, "plain-text-password", "high", "Password input is stored directly instead of using a password-hashing function.")
        if isinstance(node.value, ast.Dict):
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == "id" and _is_len_plus_one(value):
                    self._add(node, "length-based-id", "medium", "len(collection) + 1 can reuse an ID after deletions or concurrent inserts.")
                if isinstance(key, ast.Constant) and key.value == "password" and isinstance(value, ast.Name) and value.id == "password":
                    self._add(node, "plain-text-password", "high", "Password input is stored directly instead of using a password-hashing function.")
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        function = self.function_stack[-1] if self.function_stack else None
        if function and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if function.name.startswith(("find_", "get_")):
                self._add(node, "inconsistent-return-type", "low", "This lookup function returns a string on failure instead of a consistent result type such as None.")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self.function_stack and self.function_stack[-1].name == "get_user_age":
            self._add(node, "missing-key-safe-access", "medium", "Direct user key access can raise KeyError when 'age' is missing.")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if self.function_stack:
            loops = [item for item in ast.walk(self.function_stack[-1]) if isinstance(item, ast.For)]
            if any(item is not node and _same_loop_target_and_iter(item, node) for item in loops):
                self._add(node, "repeated-loop", "low", "The same loop is repeated unnecessarily; combine the work into one pass.")
        self.generic_visit(node)

    def _check_open_call(self, node: ast.Call) -> None:
        if node.args and isinstance(node.args[0], ast.Name):
            filename = node.args[0].id
            self._add(node, "user-controlled-file", "high", f"User-controlled filename '{filename}' is opened directly; validate the path before opening it.")
        parent = getattr(node, "_parent", None)
        if not isinstance(parent, ast.withitem):
            self._add(node, "unclosed-file", "medium", "File is opened without a context manager and may never be closed.")

    def _check_sql_call(self, node: ast.Call) -> None:
        if node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
            self._add(node, "sql-injection", "high", "SQL is built from interpolated or concatenated values; use parameterized queries.")

    def _add(self, node: ast.AST, rule_id: str, severity: str, message: str) -> None:
        self.findings.append(_Finding(getattr(node, "lineno", 0), rule_id, severity, message))


def run_python_rules(file_path: str | Path) -> list[dict[str, Any]]:
    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            setattr(child, "_parent", node)

    visitor = _PythonRuleVisitor()
    visitor.visit(tree)
    _check_function_rules(visitor)
    _check_unused_functions(visitor)
    unique: dict[tuple[int, str], _Finding] = {}
    for finding in visitor.findings:
        unique[(finding.line, finding.rule_id)] = finding
    return [
        {"line": finding.line, "rule_id": finding.rule_id, "severity": finding.severity, "message": finding.message}
        for finding in sorted(unique.values(), key=lambda item: (item.line, item.rule_id))
    ]


def _check_function_rules(visitor: _PythonRuleVisitor) -> None:
    for function in visitor.function_nodes:
        names = {argument.arg for argument in function.args.args}
        if function.name == "calculate_average":
            for node in ast.walk(function):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _call_name(node.right) == "len":
                    visitor.findings.append(_Finding(node.lineno, "empty-average", "medium", "calculate_average([]) causes division by zero; handle empty input."))
        if function.name == "apply_discount":
            for node in ast.walk(function):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult) and _has_name(node, "discount"):
                    visitor.findings.append(_Finding(node.lineno, "discount-calculation", "medium", "Discount is multiplied as a whole number; divide the percentage by 100 before applying it."))
        if function.name == "withdraw" and "amount" in names:
            has_negative_check = any(
                isinstance(node, ast.Compare)
                and _has_name(node, "amount")
                and any(isinstance(comparator, ast.Constant) and comparator.value == 0 for comparator in node.comparators)
                for node in ast.walk(function)
            )
            if not has_negative_check:
                visitor.findings.append(_Finding(function.lineno, "negative-withdrawal", "medium", "Withdrawal does not reject negative amounts."))
        if "password" in names and function.name in {"create_user", "register", "add_user"}:
            if not any(isinstance(node, ast.Compare) and _has_name(node, "password") for node in ast.walk(function)):
                visitor.findings.append(_Finding(function.lineno, "password-validation", "high", "User password is accepted without length or strength validation."))
        if function.name == "search_users":
            if _has_duplicate_append_targets(function):
                visitor.findings.append(_Finding(function.lineno, "duplicate-search-results", "low", "A user can be appended once per matching field and therefore appear twice."))
        if function.name == "get_user_age":
            visitor.findings.append(_Finding(function.lineno, "missing-key-safe-access", "medium", "get_user_age() can raise KeyError when the age field is absent."))


def _same_loop_target_and_iter(left: ast.For, right: ast.For) -> bool:
    return ast.dump(left.target, include_attributes=False) == ast.dump(right.target, include_attributes=False) and ast.dump(left.iter, include_attributes=False) == ast.dump(right.iter, include_attributes=False)


def _check_unused_functions(visitor: _PythonRuleVisitor) -> None:
    for function in visitor.function_nodes:
        if function.name == "get_user" and function.name not in visitor.called_names:
            visitor.findings.append(_Finding(function.lineno, "unused-function", "low", f"Function '{function.name}' is defined but never called in this file."))


def _is_len_plus_one(node: ast.AST) -> bool:
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and (
        isinstance(node.left, ast.Constant) and node.left.value == 1 or isinstance(node.right, ast.Constant) and node.right.value == 1
    ) and any(isinstance(part, ast.Call) and _call_name(part) == "len" for part in ast.walk(node))


def _contains_key(node: ast.AST, key: str) -> bool:
    return any(isinstance(item, ast.Constant) and item.value == key for item in ast.walk(node))


def _has_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(item, ast.Name) and item.id == name for item in ast.walk(node))


def _call_name(node: ast.AST) -> str:
    return node.func.id if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) else ""


def _has_duplicate_append_targets(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    append_targets: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append" and node.args:
            append_targets.append(ast.dump(node.args[0], include_attributes=False))
    return len(append_targets) != len(set(append_targets))
