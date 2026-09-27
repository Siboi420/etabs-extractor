#!/usr/bin/env bash
#
# run_gui.sh — launch the etabs_extractor GUI (base reactions + plotting).
#
# The GUI talks to ETABS over COM on Windows, but WSL can execute the Windows
# Python interpreter directly, so this launcher bridges the gap exactly like
# run_etabs.sh:
#
#   1. Finds the Windows Python interpreter (robust discovery).
#   2. Converts POSIX /mnt/d/... arguments to D:\... so path fields behave
#      naturally.
#   3. Runs `python -m etabs_extractor.gui` under it.
#
# Requires ETABS running (or use the GUI's "Attach (not launch)" / launch
# option), a display for the customtkinter window, and `customtkinter`
# installed on the Windows Python (pip install customtkinter).
#
# Usage:
#   ./run_gui.sh
#   ./run_gui.sh -- (pass-through args, if any)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- 1. Locate the Windows Python interpreter -----------------------------
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
    echo "run_gui.sh: could not locate the Windows Python interpreter." >&2
    echo "  Set WIN_PY=<path-to-windows-python.exe> or place it at" >&2
    echo "  $HERE/windows_python.exe" >&2
    exit 1
fi

# ---- 2. Convert POSIX /mnt/<drive>/... arguments to D:\... ---------------
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

# ---- 3. Run the GUI under the Windows interpreter -------------------------
cd "$HERE"
exec "$WIN_PY" -m etabs_extractor.gui "${args[@]}"
