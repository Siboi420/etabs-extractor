#!/usr/bin/env bash
#
# run_etabs.sh — run etabs_extractor against a LIVE ETABS via the Windows
# interpreter.  The package is COM-only on Windows, but WSL can execute the
# Windows Python directly, so this launcher bridges the gap:
#
#   1. Finds the Windows Python interpreter (robust discovery, not a hardcoded
#      versioned name).
#   2. Runs `python -m etabs_extractor` under it.
#   3. Converts POSIX /mnt/d/... arguments to D:\... so you can pass paths the
#      natural WSL way and they still work over COM.
#
# Usage (mirrors python -m etabs_extractor):
#   ./run_etabs.sh --list-only
#   ./run_etabs.sh --model /mnt/d/.../model.EDB --combos "LRFD 4" "ASD 4" --output out
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- 1. Locate the Windows Python interpreter -----------------------------
#
# Robust discovery: try the canonical python.exe in a few likely spots rather
# than hardcoding a versioned filename (that path typo was the original
# first-try failure).  First hit wins.
WIN_PY=""
for cand in \
    "/mnt/c/Users/user/AppData/Local/Python/bin/python.exe" \
    "/mnt/c/Users/user/AppData/Local/Programs/Python/python.exe"; do
    if [ -x "$cand" ] && "$cand" --version >/dev/null 2>&1; then
        WIN_PY="$cand"
        break
    fi
done
# Fall back to whatever the launcher is named, if colocated.
if [ -z "$WIN_PY" ] && [ -x "$HERE/windows_python.exe" ]; then
    WIN_PY="$HERE/windows_python.exe"
fi

if [ -z "$WIN_PY" ]; then
    echo "run_etabs.sh: could not locate the Windows Python interpreter." >&2
    echo "  Set WIN_PY=<path-to-windows-python.exe> or place it at" >&2
    echo "  $HERE/windows_python.exe" >&2
    exit 1
fi

# ---- 2. Convert POSIX /mnt/<drive>/... arguments to D:\... ---------------
# The package already does this at the model layer, but doing it here too
# means `--model /mnt/d/foo` and `--output /tmp/x` "just work" even when the
# argument would otherwise be passed through as a literal POSIX path.
args=()
for a in "$@"; do
    if [[ "$a" == /mnt/[a-zA-Z]/* ]]; then
        drive="${a:5:1}"
        upper="${drive^^}"
        rest="${a:7}"
        args+=("${upper}:\\${rest//\//\\}")
    else
        args+=("$a")
    fi
done

# ---- 3. Run the package under the Windows interpreter --------------------
#
# cd into the package root first: Windows Python can already import it via the
# WSL mount (editable install resolves from anywhere), but running from a
# UNC-qualified cwd confuses cmd.exe subprocesses; a normal Linux cwd avoids
# that entirely.
cd "$HERE"
exec "$WIN_PY" -m etabs_extractor "${args[@]}"
