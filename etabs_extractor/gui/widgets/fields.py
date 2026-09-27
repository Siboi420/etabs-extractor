"""Basic labeled field widgets for the etabs_extractor GUI.

All are thin wrappers over customtkinter widgets; importing this module does
**not** require a display (customtkinter/Tk are only used at instantiation
time).
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

_LABEL_WIDTH = 96


class LabeledEntry(ctk.CTkFrame):
    """A label + text entry row."""

    def __init__(self, master, label: str, default: str = "", *, width: int = 220) -> None:
        super().__init__(master, fg_color="transparent")
        self.label = ctk.CTkLabel(self, text=label, anchor="w", width=_LABEL_WIDTH)
        self.label.pack(side="left", padx=(0, 6))
        self.var = ctk.StringVar(value=str(default))
        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(str(value))


class DirectoryField(ctk.CTkFrame):
    """A label above a text entry + "Browse" button picking a directory.

    Stacked (label row, then entry+Browse row) rather than packed in one
    horizontal row: at the sidebar's ~340px width, a single row of
    label(96) + entry(220) + button(72) left the Browse button laid out
    past the frame's right edge (unmapped — never actually drawn/clickable).
    Stacking keeps the button always visible.
    """

    def __init__(self, master, label: str, default: str = "", *, width: int = 220) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.label = ctk.CTkLabel(self, text=label, anchor="w")
        self.label.grid(row=0, column=0, columnspan=2, sticky="w")
        self.var = ctk.StringVar(value=str(default))
        self.entry = ctk.CTkEntry(self, textvariable=self.var)
        self.entry.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.btn = ctk.CTkButton(self, text="Browse", command=self._browse, width=72)
        self.btn.grid(row=1, column=1, sticky="e")

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var.get().strip() or None)
        if chosen:
            self.var.set(chosen)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(str(value))


class FileField(ctk.CTkFrame):
    """A label above a text entry + "Browse" button picking a file path
    (optionally filtered by a set of extensions).

    Stacked layout — see :class:`DirectoryField` for why.
    """

    def __init__(
        self,
        master,
        label: str,
        default: str = "",
        *,
        width: int = 220,
        filetypes: str = "All files",
        patterns: tuple[str, ...] = ("*.*",),
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._patterns = patterns
        self._filetypes_text = filetypes
        self.grid_columnconfigure(0, weight=1)
        self.label = ctk.CTkLabel(self, text=label, anchor="w")
        self.label.grid(row=0, column=0, columnspan=2, sticky="w")
        self.var = ctk.StringVar(value=str(default))
        self.entry = ctk.CTkEntry(self, textvariable=self.var)
        self.entry.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.btn = ctk.CTkButton(self, text="Browse", command=self._browse, width=72)
        self.btn.grid(row=1, column=1, sticky="e")

    def _browse(self) -> None:
        patterns: list[tuple[str, str]] = []
        for p in self._patterns:
            patterns.append((f"{self._filetypes_text} ({p})", p))
        patterns.append(("All files", "*.*"))
        current = self.var.get().strip()
        initialdir = str(Path(current).parent) if current else None
        chosen = filedialog.askopenfilename(filetypes=patterns, initialdir=initialdir)
        if chosen:
            self.var.set(chosen)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(str(value))


class Section(ctk.CTkFrame):
    """A titled card grouping related controls (replaces ``ttk.LabelFrame``,
    which customtkinter has no equivalent for).

    Usage: create it, then pack/grid children into ``section.body`` (not
    ``section`` itself).
    """

    def __init__(self, master, title: str, **kwargs) -> None:
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        super().__init__(master, **kwargs)
        self._title_label = ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(weight="bold"), anchor="w"
        )
        self._title_label.pack(fill="x", padx=10, pady=(8, 2))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
