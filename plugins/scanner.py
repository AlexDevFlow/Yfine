"""
Security scanner for Yfine plugins.

Analyzes plugin source files for potentially dangerous patterns before
installation. Returns a structured report with severity levels so the
user can make an informed decision.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Severity = Literal["critical", "warning", "info"]


@dataclass
class Finding:
    severity: Severity
    category: str
    message: str
    file: str
    line: int | None = None


@dataclass
class ScanReport:
    plugin_id: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")

    @property
    def is_safe(self) -> bool:
        return self.critical_count == 0 and self.warning_count == 0

    def to_dict(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "is_safe": self.is_safe,
            "counts": {
                "critical": self.critical_count,
                "warning": self.warning_count,
                "info": self.info_count,
            },
            "findings": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "file": f.file,
                    "line": f.line,
                }
                for f in self.findings
            ],
        }


# --- Pattern definitions ---

# Dangerous module imports
_CRITICAL_IMPORTS = {
    "subprocess": "Can execute arbitrary system commands",
    "shutil": "Can delete/move files on the filesystem",
    "ctypes": "Can call arbitrary C functions",
    "multiprocessing": "Can spawn system processes",
    "importlib": "Can dynamically import any module, bypassing scanner checks",
    "pickle": "Deserialization can execute arbitrary code",
    "marshal": "Deserialization can execute arbitrary code",
    "code": "Provides interactive Python console — arbitrary code execution",
    "codeop": "Can compile arbitrary code for execution",
}

_WARNING_IMPORTS = {
    "requests": "Can make external HTTP requests",
    "httpx": "Can make external HTTP requests",
    "urllib": "Can make external HTTP requests",
    "urllib.request": "Can make external HTTP requests",
    "aiohttp": "Can make external HTTP requests",
    "socket": "Can open network connections",
    "smtplib": "Can send emails",
    "ftplib": "Can connect to FTP servers",
    "paramiko": "Can make SSH connections",
    "boto3": "Can access AWS services",
    "google.cloud": "Can access Google Cloud services",
    "yaml": "Unsafe YAML deserialization can execute code (yaml.load)",
    "shelve": "Uses pickle internally — deserialization risk",
    "xmlrpc": "Can make remote procedure calls",
}

# Dangerous function calls
_CRITICAL_CALLS = {
    "exec": "Executes arbitrary Python code",
    "eval": "Evaluates arbitrary Python expressions",
    "compile": "Can compile and execute arbitrary code",
    "__import__": "Dynamic import can load any module",
    "globals": "Can modify global state",
    "breakpoint": "Can open interactive debugger in host process",
}

_WARNING_CALLS = {
    "getattr": "Dynamic attribute access can bypass static analysis",
    "vars": "Can enumerate object attributes to discover dangerous functions",
    "dir": "Can enumerate object attributes to discover dangerous functions",
}

# getattr() on builtins is a common scanner evasion — promote to critical
_CRITICAL_GETATTR_TARGETS = {"builtins", "__builtins__"}

_CRITICAL_ATTR_CALLS = {
    ("os", "system"): "Executes system shell commands",
    ("os", "popen"): "Executes system shell commands",
    ("os", "exec"): "Replaces the current process",
    ("os", "execv"): "Replaces the current process",
    ("os", "execvp"): "Replaces the current process",
    ("os", "remove"): "Can delete files",
    ("os", "unlink"): "Can delete files",
    ("os", "rmdir"): "Can delete directories",
    ("os", "rename"): "Can rename/move files",
    ("os", "environ"): "Can access/modify environment variables (secrets, config)",
    ("sys", "exit"): "Can terminate the application",
    ("shutil", "rmtree"): "Can delete entire directory trees",
    ("shutil", "move"): "Can move files outside plugin directory",
    ("pickle", "loads"): "Deserialization can execute arbitrary code",
    ("pickle", "load"): "Deserialization can execute arbitrary code",
    ("marshal", "loads"): "Deserialization can execute arbitrary code",
    ("marshal", "load"): "Deserialization can execute arbitrary code",
    ("yaml", "load"): "Unsafe YAML deserialization can execute code",
    ("yaml", "unsafe_load"): "Unsafe YAML deserialization can execute code",
    ("base64", "b64decode"): "Base64 decoding can hide malicious payloads from static analysis",
    ("base64", "decodebytes"): "Base64 decoding can hide malicious payloads from static analysis",
}

# Dangerous pathlib.Path method calls
_WARNING_PATH_METHODS = {
    "read_text", "read_bytes", "write_text", "write_bytes",
    "unlink", "rmdir", "mkdir", "rename", "replace", "symlink_to",
    "hardlink_to", "chmod", "touch",
}

# SQL injection / dangerous raw SQL patterns
_SQL_PATTERNS = [
    (r"\bDROP\s+TABLE\b", "critical", "DROP TABLE statement found"),
    (r"\bDROP\s+DATABASE\b", "critical", "DROP DATABASE statement found"),
    (r"\bDELETE\s+FROM\s+(?!{plugin_id})", "warning", "DELETE on non-plugin table"),
    (r"\bALTER\s+TABLE\b", "warning", "ALTER TABLE statement found"),
    (r"\bTRUNCATE\b", "critical", "TRUNCATE statement found"),
    (r"\bUPDATE\s+(?!{plugin_id})", "warning", "UPDATE on non-plugin table"),
]

# Network / URL patterns in strings
_URL_PATTERN = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)

# File operation patterns (outside of normal plugin use)
_FILE_PATTERNS = [
    (r"\bopen\s*\(", "info", "File open() call — verify it only accesses plugin files"),
]


class PluginScanner:
    def __init__(self, plugin_dir: Path, plugin_id: str):
        self.plugin_dir = plugin_dir
        self.plugin_id = plugin_id
        self.report = ScanReport(plugin_id=plugin_id)

    def scan(self) -> ScanReport:
        """Run all scans on the plugin directory."""
        py_files = list(self.plugin_dir.glob("**/*.py"))

        for py_file in py_files:
            rel_path = str(py_file.relative_to(self.plugin_dir))
            source = py_file.read_text(encoding="utf-8", errors="ignore")

            self._scan_ast(source, rel_path)
            self._scan_sql_patterns(source, rel_path)
            self._scan_urls(source, rel_path)
            self._scan_file_patterns(source, rel_path)

        # Scan non-Python files for embedded scripts or suspicious content
        for html_file in self.plugin_dir.glob("**/*.html"):
            rel_path = str(html_file.relative_to(self.plugin_dir))
            source = html_file.read_text(encoding="utf-8", errors="ignore")
            self._scan_html(source, rel_path)

        # Flag compiled bytecode files that bypass source analysis
        for pyc_file in self.plugin_dir.glob("**/*.pyc"):
            rel_path = str(pyc_file.relative_to(self.plugin_dir))
            self._add("critical", "compiled_code",
                       "Compiled .pyc file cannot be analyzed — may contain malicious code",
                       rel_path)
        for pyo_file in self.plugin_dir.glob("**/*.pyo"):
            rel_path = str(pyo_file.relative_to(self.plugin_dir))
            self._add("critical", "compiled_code",
                       "Compiled .pyo file cannot be analyzed — may contain malicious code",
                       rel_path)

        # Flag native compiled extensions that bypass all static analysis
        for ext in (".so", ".pyd", ".dll", ".dylib"):
            for native_file in self.plugin_dir.glob(f"**/*{ext}"):
                rel_path = str(native_file.relative_to(self.plugin_dir))
                self._add("critical", "native_extension",
                           f"Native compiled extension ({ext}) cannot be analyzed "
                           "— may contain malicious code",
                           rel_path)

        # Permanent disclosure: scanner is best-effort, not a sandbox
        self._add("info", "scanner_limitations",
                   "This scanner uses static analysis and can be bypassed by "
                   "determined authors. Only install plugins from sources you trust.",
                   "—")

        return self.report

    def _add(self, severity: Severity, category: str, message: str,
             file: str, line: int | None = None):
        self.report.findings.append(
            Finding(severity=severity, category=category,
                    message=message, file=file, line=line)
        )

    def _scan_ast(self, source: str, file: str):
        """Use AST parsing for accurate Python analysis."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            self._add("warning", "parse_error",
                       "Could not parse Python file — manual review recommended",
                       file)
            return

        for node in ast.walk(tree):
            self._check_imports(node, file)
            self._check_calls(node, file)
            self._check_attribute_access(node, file)

    def _check_imports(self, node: ast.AST, file: str):
        """Check for dangerous module imports."""
        modules = []

        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules = [node.module]

        for mod in modules:
            # Check the base module name
            base = mod.split(".")[0]

            if base in _CRITICAL_IMPORTS:
                self._add("critical", "dangerous_import",
                           f"import {mod} — {_CRITICAL_IMPORTS[base]}",
                           file, getattr(node, "lineno", None))
            elif mod in _WARNING_IMPORTS or base in _WARNING_IMPORTS:
                desc = _WARNING_IMPORTS.get(mod) or _WARNING_IMPORTS.get(base, "")
                self._add("warning", "network_import",
                           f"import {mod} — {desc}",
                           file, getattr(node, "lineno", None))

            # os module: warning (it has both safe and unsafe uses)
            if base == "os":
                self._add("warning", "os_import",
                           "import os — can access filesystem and environment",
                           file, getattr(node, "lineno", None))

    def _check_calls(self, node: ast.AST, file: str):
        """Check for dangerous function calls."""
        if not isinstance(node, ast.Call):
            return

        # Direct function calls: exec(), eval(), etc.
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in _CRITICAL_CALLS:
                self._add("critical", "dangerous_call",
                           f"{name}() — {_CRITICAL_CALLS[name]}",
                           file, getattr(node, "lineno", None))
            elif name == "getattr" and len(node.args) >= 1:
                # getattr(__builtins__, ...) is a scanner evasion technique
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Name) and first_arg.id in _CRITICAL_GETATTR_TARGETS:
                    self._add("critical", "scanner_evasion",
                               f"getattr({first_arg.id}, ...) — can dynamically access "
                               "any builtin, bypassing static analysis",
                               file, getattr(node, "lineno", None))
                else:
                    self._add("warning", "dynamic_access",
                               f"{name}() — {_WARNING_CALLS[name]}",
                               file, getattr(node, "lineno", None))
            elif name in _WARNING_CALLS:
                self._add("warning", "dynamic_access",
                           f"{name}() — {_WARNING_CALLS[name]}",
                           file, getattr(node, "lineno", None))
            elif name == "type" and len(node.args) == 3:
                # type(name, bases, dict) creates a class dynamically
                self._add("critical", "scanner_evasion",
                           "type() with 3 args — dynamic class creation "
                           "can bypass static analysis",
                           file, getattr(node, "lineno", None))

        # Attribute calls: os.system(), sys.exit(), etc.
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if isinstance(node.func.value, ast.Name):
                obj = node.func.value.id
                key = (obj, attr)
                if key in _CRITICAL_ATTR_CALLS:
                    self._add("critical", "dangerous_call",
                               f"{obj}.{attr}() — {_CRITICAL_ATTR_CALLS[key]}",
                               file, getattr(node, "lineno", None))

                # builtins.__import__() or __builtins__.__import__()
                if obj in ("builtins", "__builtins__") and attr == "__import__":
                    self._add("critical", "dangerous_call",
                               f"{obj}.__import__() — dynamic import bypasses scanner",
                               file, getattr(node, "lineno", None))

                # pathlib.Path dangerous methods (covers patterns like Path(...).write_text())
                if attr in _WARNING_PATH_METHODS:
                    self._add("warning", "file_access",
                               f".{attr}() — pathlib file operation, verify it only accesses plugin files",
                               file, getattr(node, "lineno", None))

            # Chained attribute calls: pathlib method on any object
            elif isinstance(node.func.value, ast.Call) and attr in _WARNING_PATH_METHODS:
                self._add("warning", "file_access",
                           f".{attr}() — possible pathlib file operation",
                           file, getattr(node, "lineno", None))

            # Check for raw SQL execution: session.exec(text(...))
            if attr == "execute" or (attr == "exec" and isinstance(node.func.value, ast.Name)):
                for arg in node.args:
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                        if arg.func.id == "text":
                            self._add("warning", "raw_sql",
                                       "Raw SQL via text() — verify query is safe",
                                       file, getattr(node, "lineno", None))

            # metadata.drop_all()
            if attr == "drop_all":
                self._add("critical", "db_destructive",
                           "drop_all() — can destroy all database tables",
                           file, getattr(node, "lineno", None))

    def _check_attribute_access(self, node: ast.AST, file: str):
        """Check for suspicious attribute access patterns."""
        if not isinstance(node, ast.Attribute):
            return

        # __subclasses__() — classic sandbox escape (object.__subclasses__())
        if node.attr == "__subclasses__":
            self._add("critical", "scanner_evasion",
                       "__subclasses__() — can discover and instantiate internal classes "
                       "to bypass static analysis",
                       file, getattr(node, "lineno", None))

        # Check for engine direct access
        if isinstance(node.value, ast.Name) and node.value.id == "engine":
            if node.attr in ("execute", "connect", "raw_connection"):
                self._add("warning", "direct_engine",
                           f"Direct engine.{node.attr}() — use get_session dependency instead",
                           file, getattr(node, "lineno", None))

        # Check for os.environ access (non-call form, e.g. os.environ["KEY"])
        if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "environ":
            self._add("warning", "env_access",
                       "os.environ access — can read secrets and config",
                       file, getattr(node, "lineno", None))

    def _scan_sql_patterns(self, source: str, file: str):
        """Scan for dangerous SQL patterns in string literals."""
        for i, line in enumerate(source.splitlines(), 1):
            for pattern, severity, message in _SQL_PATTERNS:
                p = pattern.replace("{plugin_id}", self.plugin_id)
                if re.search(p, line, re.IGNORECASE):
                    self._add(severity, "sql_pattern", message, file, i)

    def _scan_urls(self, source: str, file: str):
        """Detect external URLs in source code."""
        for i, line in enumerate(source.splitlines(), 1):
            urls = _URL_PATTERN.findall(line)
            for url in urls:
                # Skip common safe URLs (docs, comments, etc.)
                if any(safe in url for safe in [
                    "localhost", "127.0.0.1", "boxicons.com",
                    "fonts.googleapis.com", "fonts.gstatic.com",
                    "themeselection.com",
                ]):
                    continue
                self._add("warning", "external_url",
                           f"External URL: {url[:80]}",
                           file, i)

    def _scan_file_patterns(self, source: str, file: str):
        """Scan for file operation patterns."""
        for i, line in enumerate(source.splitlines(), 1):
            for pattern, severity, message in _FILE_PATTERNS:
                if re.search(pattern, line):
                    # Skip if it's opening locale files (normal plugin behavior)
                    if "locales" in line or "manifest" in line:
                        continue
                    self._add(severity, "file_access", message, file, i)

    def _scan_html(self, source: str, file: str):
        """Scan HTML templates for suspicious patterns."""
        for i, line in enumerate(source.splitlines(), 1):
            # External script/link tags
            if re.search(r'<script[^>]+src\s*=\s*["\']https?://', line, re.IGNORECASE):
                self._add("warning", "external_script",
                           "External script loaded from remote URL",
                           file, i)
            if re.search(r'<link[^>]+href\s*=\s*["\']https?://', line, re.IGNORECASE):
                # Skip font links (common and safe)
                if "fonts.googleapis.com" not in line and "fonts.gstatic.com" not in line:
                    self._add("info", "external_resource",
                               "External resource loaded from remote URL",
                               file, i)

            # Inline event handlers that could be suspicious
            urls = _URL_PATTERN.findall(line)
            for url in urls:
                if any(safe in url for safe in [
                    "localhost", "127.0.0.1", "/static/",
                    "fonts.googleapis.com", "fonts.gstatic.com",
                    "boxicons.com", "themeselection.com",
                ]):
                    continue
                self._add("info", "external_url",
                           f"External URL in template: {url[:80]}",
                           file, i)


def scan_plugin(plugin_dir: Path, plugin_id: str) -> ScanReport:
    """Convenience function to scan a plugin directory."""
    scanner = PluginScanner(plugin_dir, plugin_id)
    return scanner.scan()
