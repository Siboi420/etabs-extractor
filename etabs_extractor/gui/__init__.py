"""Interactive GUI for etabs_extractor (base-reaction extraction + plotting).

The GUI is a thin view over the existing library; it never imports COM or
matplotlib at module top level.  ``tkinter`` is imported lazily inside the
entry point, so importing this package (or any of its submodules) is safe on
any platform — no display, no comtypes required.
"""

from __future__ import annotations


def run_gui() -> int:
    """Launch the etabs_extractor GUI.

    Imports tkinter and the application class lazily (so importing this
    package never forces a display).  Returns an exit code (0 on clean
    close)."""
    from etabs_extractor.gui.app import EtabsExtractorApp  # noqa: PLC0415

    try:
        app = EtabsExtractorApp()
    except Exception as exc:  # noqa: BLE001 - surface a clear, one-line error
        import sys

        print(f"[etabs-extractor-gui] could not start: {exc}", file=sys.stderr)
        return 1
    app.mainloop()
    return 0


__all__ = ["run_gui"]