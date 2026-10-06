#!/usr/bin/env python3
"""Fail if the repository contains operational data, secrets or model weights.

Used by CI (all tracked files) and by the pre-commit hook (``--staged``).
Policy: spreadsheets, databases, evidence and exports never belong in git, not even
"synthetic" ones. Test fixtures are generated at test time instead.
"""

import re
import subprocess
import sys
from pathlib import PurePosixPath

FORBIDDEN_SUFFIXES = {
    ".xlsx", ".xls", ".xlsm", ".ods", ".csv", ".tsv",
    ".db", ".sqlite", ".sqlite3", ".dump",
    ".pem", ".key", ".p12", ".jks", ".keystore",
    ".pt", ".onnx", ".safetensors", ".ckpt",
    ".apk", ".aab",
}
FORBIDDEN_DIRS = {"data", "uploads", "evidence", "samples", "exports", "models", "secrets"}
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
]
MAX_SCAN_BYTES = 2_000_000


def tracked(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"] if staged else ["git", "ls-files", "-z"]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    return [p for p in out.decode().split("\0") if p]


def violations_for(path: str, read=lambda p: open(p, "rb").read(MAX_SCAN_BYTES)) -> list[str]:
    pure = PurePosixPath(path)
    problems = []
    name = pure.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        problems.append("environment file")
    if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
        problems.append(f"forbidden file type {pure.suffix.lower()}")
    if FORBIDDEN_DIRS & set(pure.parts[:-1]):
        problems.append("file under a data directory")
    try:
        content = read(path)
    except OSError:
        return problems
    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            problems.append("looks like a private key or cloud credential")
            break
    return problems


def main(argv: list[str]) -> int:
    bad = {p: v for p in tracked("--staged" in argv) if (v := violations_for(p))}
    for path, problems in sorted(bad.items()):
        print(f"BLOCKED  {path}: {', '.join(problems)}")
    if bad:
        print(f"\n{len(bad)} file(s) must not be committed. See docs/data-protection.md.")
        return 1
    print("data guard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
