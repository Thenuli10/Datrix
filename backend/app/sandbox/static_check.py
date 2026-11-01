"""AST scan of generated code before it runs (PLAN.md §3 Stage 4, §5).

Defence in depth only: the Docker sandbox is the real isolation boundary.
"""
from __future__ import annotations

import ast

MAX_CODE_BYTES = 200 * 1024

BANNED_MODULES = frozenset({
    "subprocess", "socket", "requests", "urllib", "urllib3", "http", "httpx", "aiohttp",
    "ftplib", "smtplib", "telnetlib", "ctypes", "multiprocessing", "pty", "importlib",
    "builtins", "paramiko",
})
BANNED_CALLS = frozenset({"eval", "exec", "compile", "__import__", "breakpoint"})
BANNED_NAMES = frozenset({"__builtins__"})
BANNED_ATTRS = frozenset({"__subclasses__", "__globals__", "__code__"})
BANNED_OS = frozenset({"system", "popen", "fork", "forkpty", "kill", "killpg"})
BANNED_OS_PREFIXES = ("exec", "spawn", "posix_spawn")
BANNED_SHUTIL = frozenset({"rmtree"})
ALLOWED_PATH_PREFIXES = ("/input", "/output", "/model", "/tmp")


def _os_banned(name: str) -> bool:
    return name in BANNED_OS or name.startswith(BANNED_OS_PREFIXES)


def _literal_path_ok(path: str) -> bool:
    """Literal paths given to open() must stay inside the mounted sandbox dirs."""
    if ".." in path.replace("\\", "/").split("/"):
        return False
    if path.startswith(("/", "\\")) or (len(path) > 1 and path[1] == ":"):
        return path.replace("\\", "/").startswith(ALLOWED_PATH_PREFIXES)
    return True


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.issues: list[str] = []

    def _add(self, node: ast.AST, msg: str) -> None:
        self.issues.append(f"line {getattr(node, 'lineno', '?')}: {msg}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in BANNED_MODULES:
                self._add(node, f"import of banned module '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = (node.module or "").split(".")[0]
        if mod in BANNED_MODULES:
            self._add(node, f"import from banned module '{node.module}'")
        for alias in node.names:
            if (mod == "os" and _os_banned(alias.name)) or (mod == "shutil" and alias.name in BANNED_SHUTIL):
                self._add(node, f"import of banned function '{mod}.{alias.name}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
            self._add(node, f"call to banned builtin '{func.id}()'")
        if isinstance(func, ast.Name) and func.id == "open" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and not _literal_path_ok(arg.value):
                self._add(node, f"open() of path '{arg.value}' outside /input, /output, /model or /tmp")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            base = node.value.id
            if base == "os" and _os_banned(node.attr):
                self._add(node, f"use of banned function 'os.{node.attr}'")
            elif base == "shutil" and node.attr in BANNED_SHUTIL:
                self._add(node, f"use of banned function 'shutil.{node.attr}'")
        if node.attr in BANNED_ATTRS:
            self._add(node, f"access to banned attribute '{node.attr}'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BANNED_NAMES:
            self._add(node, f"use of banned name '{node.id}'")
        self.generic_visit(node)


def check_code(source: str) -> list[str]:
    """Return human-readable problems with `source`; an empty list means it may run."""
    size = len(source.encode("utf-8"))
    if size > MAX_CODE_BYTES:
        return [f"code is {size // 1024} KB; the limit is {MAX_CODE_BYTES // 1024} KB"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: syntax error: {exc.msg}"]
    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.issues
