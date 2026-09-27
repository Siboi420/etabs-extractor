"""Runner that executes the (COM) extraction on a background thread.

Keeps the Tk main thread responsive while the library does its work, and
initializes COM *inside* the worker thread (correct apartment usage).  It
posts ``(kind, payload)`` messages onto a :class:`queue.Queue` for the UI to
drain:

* ``("log", message)``        — progress/informational line
* ``("progress", fraction)``  — 0.0..1.0 progress-bar value
* *On completion:*
* ``("result", {df, per_load, records, output_dir, tag})`` — successful extraction
* ``("error", message)``      — a failure
* ``("done", None)``          — thread finished (always sent last)
"""

from __future__ import annotations

import queue
import threading


class BackgroundRunner:
    """Run a callable in a background thread, delivering results to a queue.

    On Windows this initialises COM on the worker thread (`CoInitialize`) so
    that comtypes calls succeed outside the main thread, and tears COM down
    (`CoUninitialize`) when the work is done. On non-Windows platforms
    (WSL tests) this is a harmless no-op.
    """

    # Which queue messages are "progress" style.
    def __init__(self, fn, *args, **kwargs) -> None:
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def queue(self) -> "queue.Queue":
        return self._queue

    def start(self) -> None:
        """Launch the worker thread (COM is initialised inside it)."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _co_initialize(self) -> None:
        """Initialise COM on this worker thread (Windows only).  No-op where
        comtypes is not importable (e.g. WSL tests) ."""
        try:
            import comtypes  # noqa: PLC0415
            comtypes.CoInitialize()
        except Exception:  # noqa: BLE001 - non-Windows runtimes have no COM
            pass

    def _co_uninitialize(self) -> None:
        try:
            import comtypes  # noqa: PLC0415
            comtypes.CoUninitialize()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass

    def _run(self) -> None:
        self._co_initialize()
        try:
            result = self._fn(*self._args, **self._kwargs)
            self._queue.put(("result", result))
        except Exception as exc:  # noqa: BLE001 - surface any worker failure
            self._queue.put(("error", str(exc)))
        finally:
            self._queue.put(("done", None))
            self._co_uninitialize()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


def run_extraction(settings, progress_cb=None, log_cb=None) -> dict:
    """Synchronous wrapper around :func:`service.do_extract` that posts
    progress/log callbacks.  Used both by the GUI (via the queue) and by
    tests."""

    from etabs_extractor.gui import service

    if log_cb:
        log_cb("Starting base-reaction extraction...")
    if progress_cb:
        progress_cb(0.0)

    result = service.do_extract(settings)

    if progress_cb:
        progress_cb(1.0)
    if log_cb:
        log_cb("Extraction complete.")
    return result