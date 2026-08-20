"""Basic labeled field widgets for the etabs_extractor GUI.

All are thin wrappers over standard Tk widgets; importing this module does
**not** require a display (Tk is only used at instantiation time).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from pathlib import Path


class LabeledEntry(tk.Frame):
    """A label + text entry row."""

    def __init__(self, master, label: str, default: str = "", *, width: int = 60) -> None:
        super().__init__(master)
        self.label = tk.Label(self, text=label, anchor="w", width=14)
        self.label.pack(side="left", padx=(0, 4))
        self.var = tk.StringVar(value=str(default))
        self.entry = tk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(str(value))


class DirectoryField(tk.Frame):
    """A label + text entry + "Browse" button picking a directory."""

    def __init__(self, master, label: str, default: str = "", *, width: int = 60) -> None:
        super().__init__(master)
        self.label = tk.Label(self, text=label, anchor="w", width=14)
        self.label.pack(side="left", padx=(0, 4))
        self.var = tk.StringVar(value=str(default))
        self.entry = tk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        self.btn = tk.Button(self, text="Browse", command=self._browse, width=8)
        self.btn.pack(side="left", padx=(4, 0))

    def _browse(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.var.set(chosen)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(str(value))


class FileField(tk.Frame):
    """A label + text entry + "Browse" button picking a file path (optionally
    filtered by a set of extensions)."""

    def __init__(
        self,
        master,
        label: str,
        default: str = "",
        *,
        width: int = 60,
        filetypes: str = "All files",
        patterns: tuple[str, ...] = ("*.*",),
    ) -> None:
        super().__init__(master)
        self._patterns = patterns
        self._filetypes_text = filetypes
        self.label = tk.Label(self, text=label, anchor="w", width=14)
        self.label.pack(side="left", padx=(0, 4))
        self.var = tk.StringVar(value=str(default))
        self.entry = tk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        self.btn = tk.Button(self, text="Browse", command=self._browse, width=8)
        self.btn.pack(side="left", padx=(4, 0))

    def _browse(self) -> None:
        patterns: list[tuple[str, str]] = []
        for p in self._patterns:
            patterns.append((f"{self._filetypes_text} ({p})", p))
        patterns.append(("All files", "*.*"))
        chosen = filedialog.askopenfilename(filetypes=patterns)
        if chosen:
            self.var.set(chosen)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(str(value))


class SpinField(tk.Frame):
    """A label + Entry row where the value is numeric text; pack-style simple."""

    def __init__(
        self,
        master,
        label: str,
        default: str = "",
        *,
        width: int = 12,
        from_: float | None = None,
        to: float | None = None,
        increment: float | None = None,
    ) -> None:
        super().__init__(master)
        self.label = tk.Label(self, text=label, anchor="w", width=14)
        self.label.pack(side="left", padx=(0, 4))
        self.var = tk.StringVar(value=str(default))
        args: dict = {"textvariable": self.var, "width": width}
        if from_ is not None and to is not None:
            # A real Spinbox when bounds are given; otherwise a plain Entry.
            self.widget = tk.Spinbox(
                self, from_=from_, to=to,
                increment=increment if increment is not None else 1,
                **args,
            )
        else:
            self.widget = tk.Entry(self, **args)
        self.widget.pack(side="left", fill="x", expand=True)

    def get(self) -> str:
        return self.var.get()

    def set(self, value) -> None:
        self.var.set(str(value))