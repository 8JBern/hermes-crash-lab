#!/usr/bin/env bash
# Recreates the audit workspace. Requires git, uv, Python 3.13+ (harness) and network access to GitHub/PyPI.
set -euo pipefail
export CRASH_AUDIT_ROOT="${CRASH_AUDIT_ROOT:-/home/claude/audit}"   # harness scripts default to this path
A="$CRASH_AUDIT_ROOT"; mkdir -p "$A"/{src,work,evidence,scratch}; cd "$A"
git clone https://github.com/8JBern/hermes-crash-lab.git src/hermes-crash-lab
git -C src/hermes-crash-lab worktree add -f ../../work/rev-1.0.0 44c8071aa68a626e0d89d4afe697e3b7b864695e
git -C src/hermes-crash-lab worktree add -f ../../work/rev-1.0.1 9a712f9714ff5687425f0ffc9ac7eb6f9eb441cb
git clone https://github.com/NousResearch/hermes-agent.git src/hermes-agent
git -C src/hermes-agent checkout 03878a99c8b5842ab98586495dfd41b27245c58e
(cd src/hermes-agent && UV_PROJECT_ENVIRONMENT="$A/hermes-venv" uv sync --frozen --no-dev --python 3.14)
export HERMES_HOME="$A/hermes-home"; mkdir -p "$HERMES_HOME"       # disposable profile, never ~/.hermes
H="$A/hermes-venv/bin/hermes"
(cd work/rev-1.0.1 && python -m unittest discover -p 'test_*.py' -v && "$H" plugins doctor . --ci && "$H" plugins validate . --install-deps)
"$H" plugins install 8JBern/hermes-crash-lab </dev/null && "$H" plugins enable crash-lab </dev/null && "$H" plugins doctor crash-lab --ci
# copy this harness/ and proposed/ directory to $A, then:
cd "$A/harness"
python3 l1.py; python3 l23.py; python3 l4a.py; (cd "$A" && python3 harness/l4b.py)
(cd "$A" && HERMES_HOME="$A/hermes-home" hermes-venv/bin/python harness/l4c.py)
python3 l5.py; python3 mutate.py; python3 suite.py; python3 rel.py; python3 verify_proposed.py; python3 mutate_fix.py
python3 compile.py "$A/02_TEST_MATRIX.csv"
