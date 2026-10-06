#!/usr/bin/env bash
# Installs a pre-commit hook that runs the data guard on staged files.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cat > "$root/.git/hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
exec python3 "$(git rev-parse --show-toplevel)/scripts/check_no_data.py" --staged
HOOK
chmod +x "$root/.git/hooks/pre-commit"
echo "pre-commit hook installed"
