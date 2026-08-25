"""Searchable, multi-select load (combos + cases) widget for the GUI.

:class:`LoadSelectionField` is a ``tk.Frame`` presenting a read-only summary
entry ("N selected" / "all combos") that opens a ``tk.Toplevel`` popup on
click.  The popup holds a search ``ttk.Entry`` (filters items as you type) and
a scrolling checklist of items labelled ``(combo)`` / ``(case)``; checkboxes
toggle selection and a "Done" button closes the popup.  Selection persists
across opens.

The filtering/selection logic lives in the pure
:class:`~etabs_extractor.gui.state.LoadSelectionModel`, so it is unit-testable
headlessly.  This widget is view-only (acts on a model instance it owns).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import logging

from etabs_extractor.gui.state import LoadSelectionModel

logger = logging.getLogger(__name__)

_SUMMARY_EMPTY = "all combos"


class LoadSelectionField(tk.Frame):
    """A clickable field that opens a searchable multi-select checklist popup.

    Parameterised by two group kinds (default ``combo``/``case`` for load
    selection, or ``section``/``frame`` for frame selection in Frame mode):
    ``label``/``title``/``empty_summary`` set the field label, popup title and
    empty-selection summary text respectively.
    """

    def __init__(
        self,
        master,
        model: LoadSelectionModel | None = None,
        *,
        label: str = "Loads",
        title: str = "Select loads",
        empty_summary: str = _SUMMARY_EMPTY,
        kind_a: str = "combo",
        kind_b: str = "case",
    ) -> None:
        super().__init__(master)
        self._kind_a = kind_a
        self._kind_b = kind_b
        self._empty_summary = empty_summary
        self._model = (
            model
            if model is not None
            else LoadSelectionModel(kind_a=kind_a, kind_b=kind_b)
        )
        self._popup: tk.Toplevel | None = None

        self.label = tk.Label(self, text=label, anchor="w", width=14)
        self.label.pack(side="left", padx=(0, 4))
        self.entry = tk.Entry(self, state="readonly", width=54)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Button-1>", lambda e: self._open())
        self.btn = tk.Button(self, text="Select", command=self._open, width=8)
        self.btn.pack(side="left", padx=(4, 0))
        self._popup_title = title
        self._refresh_summary()

    # ------------------------------------------------------------------ api
    def set_items(self, a: list[str], b: list[str]) -> None:
        """Replace the available items (group-a + group-b names) and deselect."""
        self._model.set_items(a, b, self._kind_a, self._kind_b)
        self._refresh_summary()
        # Refresh an open popup against the new item set.
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.destroy()
            self._popup = None

    def get_selected(self) -> tuple[list[str], list[str]]:
        """Return ``(selected_a, selected_b)`` (e.g. combos/cases or sects/frame)."""
        return self._model.get_selected()

    def clear(self) -> None:
        self._model.clear()
        self._refresh_summary()

    def _selected_count(self) -> int:
        return len(self.get_selected()[0]) + len(self.get_selected()[1])

    def _refresh_summary(self) -> None:
        n = self._selected_count()
        text = f"{n} selected" if n else self._empty_summary
        self.entry.configure(state="normal")
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.entry.configure(state="readonly")

    # ---------------------------------------------------------------- popup
    def _open(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.lift()
            return
        self._popup = tk.Toplevel(self)
        self._popup.title(self._popup_title)
        self._popup.geometry("460x420")
        self._popup.transient(self.winfo_toplevel())
        self._build_popup()
        self._popup.protocol("WM_DELETE_WINDOW", self._close_popup)

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError as exc:
                logger.debug("Could not destroy load-selection popup: %s", exc)
        self._popup = None
        self._refresh_summary()

    def _build_popup(self) -> None:
        top = ttk.Frame(self._popup)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(top, textvariable=self._search_var)
        self._search_entry.pack(side="left", fill="x", expand=True, padx=6)
        self._search_var.trace_add("write", lambda *a: self._reload())

        # Scrolling checklist.
        self._list_frame = ttk.Frame(self._popup)
        self._list_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self._canvas = tk.Canvas(self._list_frame, highlightthickness=0)
        self._scroll = ttk.Scrollbar(self._list_frame, orient="vertical",
                                     command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._check_vars: dict = {}
        self._open_reload()
        self._focus_search()

        bottom = ttk.Frame(self._popup)
        bottom.pack(fill="x", padx=8, pady=6)
        ttk.Button(bottom, text="Done", command=self._close_popup).pack(side="right")

    def _focus_search(self) -> None:
        try:
            self._search_entry.focus_set()
        except tk.TclError as exc:
            logger.debug("Could not focus search entry: %s", exc)

    def _open_reload(self) -> None:
        self._reload("")

    def _reload(self, query: str | None = None) -> None:
        if query is None:
            query = self._search_var.get() if hasattr(self, "_search_var") else ""
        matches = self._model.matches(query)
        for child in self._inner.winfo_children():
            child.destroy()
        self._check_vars = {}
        for idx, it in enumerate(matches):
            var = tk.BooleanVar(value=it.selected)
            self._check_vars[idx] = var
            cb = ttk.Checkbutton(
                self._inner, text=it.display, variable=var,
                command=lambda i=idx: self._on_toggle(i),
            )
            cb.pack(anchor="w", padx=2, pady=1)

    def _on_toggle(self, index: int) -> None:
        """Map a display-index toggle back to the raw model item and persist."""
        query = self._search_var.get() if hasattr(self, "_search_var") else ""
        matches = self._model.matches(query)
        if 0 <= index < len(matches):
            item = matches[index]
            var = self._check_vars[index]
            self._model.toggle(self._model.items().index(item), var.get())
        self._refresh_summary()