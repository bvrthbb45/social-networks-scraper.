import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_no_data.py"
spec = importlib.util.spec_from_file_location("check_no_data", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

NO_CONTENT = lambda _p: b""  # noqa: E731


@pytest.mark.parametrize(
    "path",
    [
        "roster.xlsx",
        "data/soldiers.csv",
        "backend/exports/out.tsv",
        "evidence/img1.jpg",
        "uploads/a.png",
        ".env",
        ".env.production",
        "app.sqlite3",
        "dump.dump",
        "keys/server.pem",
        "release.keystore",
        "models/clip.safetensors",
        "weights.onnx",
        "app-release.apk",
        "samples/post.json",
        "secrets/jwt.txt",
    ],
)
def test_forbidden_paths_are_blocked(path):
    assert guard.violations_for(path, NO_CONTENT), path


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "backend/app/models.py",
        "docs/data-protection.md",
        "web/public/icons/icon-192.png",
        "backend/tests/test_schema.py",
        "README.md",
    ],
)
def test_normal_files_pass(path):
    assert guard.violations_for(path, NO_CONTENT) == []


def test_private_keys_and_cloud_credentials_in_content_are_blocked():
    # Built at runtime so this test file does not itself look like a leaked secret.
    key = (
        "-----BEGIN " + "PRIVATE KEY-----\nabc\n-----END " + "PRIVATE KEY-----"
    ).encode()
    cloud = ("aws=AKI" + "AABCDEFGHIJKLMNOP").encode()
    assert guard.violations_for("notes.txt", lambda _p: key)
    assert guard.violations_for("notes.txt", lambda _p: cloud)
    assert guard.violations_for("notes.txt", lambda _p: b"just text") == []


def test_end_to_end_in_a_real_git_repo(tmp_path):
    def git(*a):
        return subprocess.run(
            ["git", *a], cwd=tmp_path, check=True, capture_output=True
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "ok.py").write_text("print(1)")
    git("add", "ok.py")
    run = lambda *args: subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )  # noqa: E731
    assert run("--staged").returncode == 0
    (tmp_path / "roster.xlsx").write_bytes(b"PK")
    git("add", "-f", "roster.xlsx")  # even a force-add is caught
    bad = run("--staged")
    assert bad.returncode == 1 and "roster.xlsx" in bad.stdout
    assert run().returncode == 1  # also when scanning all tracked files
