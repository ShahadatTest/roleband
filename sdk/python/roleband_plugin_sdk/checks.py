"""Static checks a plugin must pass to load.

The host performs every request, so plugin code imports nothing that can
open a connection or start a process. This is a source scan, not a sandbox:
it reads every `.py` file under the package and reports each import of a
forbidden module (the network and process modules, their private halves,
`pip`'s vendored clients, dynamic importers), each `os.system`-style call on
the `os` module, and each `__import__`, `exec`, `eval` or `compile` call (code
the scan cannot read). Code that hides an import from the scan (an alias, a
dependency) defeats it: it is a review aid that catches honest mistakes, not
a guard against a plugin written to evade it. The plugin runs as the user,
out of process, with no OS sandbox; approving it is trusting its code. The
template's CI runs this check, and the host runs it again at install.

    python -m roleband_plugin_sdk.checks src/my_plugin   # exit 1 on a finding
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

#: A module is forbidden when it is one of these or inside one.
FORBIDDEN_MODULES = frozenset(
    {
        "_posixsubprocess",
        "_socket",
        "_ssl",
        "aiohttp",
        "asyncio",
        "builtins",
        "ctypes",
        "curl_cffi",
        "ftplib",
        "imaplib",
        "http.client",
        "http.cookiejar",
        "http.server",
        "httpcore",
        "httpx",
        "importlib",
        "logging.handlers",
        "multiprocessing",
        "nntplib",
        "os.system",
        "pip",
        "pkgutil",
        "poplib",
        "posix",
        "pty",
        "pycurl",
        "requests",
        "runpy",
        "select",
        "selectors",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",
        "subprocess",
        "telnetlib",
        "urllib.request",
        "urllib3",
        "webbrowser",
        "websocket",
        "websockets",
        "xmlrpc",
    }
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


#: `os` functions that start a process or replace this one.
FORBIDDEN_OS_CALLS = frozenset({
    "system", "popen", "fork", "forkpty", "kill", "killpg", "posix_spawn", "posix_spawnp",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
})

#: Builtins that run code the scan cannot read.
FORBIDDEN_CALLS = frozenset({"__import__", "exec", "eval", "compile"})


def _forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN_MODULES)


def scan_source(source: str, path: Path) -> list[Finding]:
    findings = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _forbidden(alias.name):
                    findings.append(Finding(path, node.lineno, f"imports {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            hit = next((n for n in names if _forbidden(n)), None)
            if hit:
                findings.append(Finding(path, node.lineno, f"imports {hit}"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            findings.append(Finding(path, node.lineno, f"calls {node.func.id}"))
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os"
              and node.attr in FORBIDDEN_OS_CALLS):
            findings.append(Finding(path, node.lineno, f"uses os.{node.attr}"))
    return findings


def scan(root: str | Path) -> list[Finding]:
    """Every finding under `root`, a package directory or one file."""
    base = Path(root)
    files = [base] if base.is_file() else sorted(base.rglob("*.py"))
    findings: list[Finding] = []
    for f in files:
        findings += scan_source(f.read_text(encoding="utf-8"), f)
    return findings


def main(argv: list[str] | None = None) -> int:
    roots = argv if argv is not None else sys.argv[1:]
    findings = [f for root in roots for f in scan(root)]
    for f in findings:
        print(f)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
