"""Plot-appearance settings frame for the etabs_extractor GUI.

Collects the plot parameters (dynamic size, fixed width/height, dpi, label
font size, units, format) into a group of widgets, and exposes
:meth:`to_settings` / :meth:`from_settings` to sync with a
:class:`~etabs_extractor.gui.state.GuiSettings`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from etabs_extractor.gui.state import FORMATS, UNITS_CHOICES, GuiSettings


class PlotSettingsFrame(ttk.LabelFrame):
    """A labelled frame hosting all plot-appearance controls."""

    def __init__(self, master, settings: GuiSettings | None = None) -> None:
        super().__init__(master, text="Plot appearance")
        self._settings = settings or GuiSettings()

        self.grid_columnconfigure(1, weight=1)

        # Dynamic size checkbox.
        self.dynamic_var = tk.BooleanVar(value=self._settings.dynamic_size)
        self.dynamic_cb = ttk.Checkbutton(
            self, text="Dynamic resolution (figure follows data)",
            variable=self.dynamic_var, command=self._sync_dim_enabled,
        )
        self.dynamic_cb.grid(row=0, column=0, columnspan=2, sticky="w", padx=4, pady=2)

        # Fixed width / height (inches), disabled while dynamic.
        self.width_var = tk.StringVar(value=str(self._settings.fig_width))
        self.height_var = tk.StringVar(value=str(self._settings.fig_height))
        self.width_entry = ttk.Entry(self, textvariable=self.width_var, width=10)
        self.height_entry = ttk.Entry(self, textvariable=self.height_var, width=10)
        ttk.Label(self, text="Width (in)").grid(row=1, column=0, sticky="e", padx=(8, 2))
        self.width_entry.grid(row=1, column=1, sticky="w", padx=2)
        ttk.Label(self, text="Height (in)").grid(row=2, column=0, sticky="e", padx=(8, 2))
        self.height_entry.grid(row=2, column=1, sticky="w", padx=2)

        # DPI.
        self.dpi_var = tk.StringVar(value=str(self._settings.dpi))
        ttk.Label(self, text="DPI").grid(row=3, column=0, sticky="e", padx=(8, 2))
        self.dpi_entry = ttk.Entry(self, textvariable=self.dpi_var, width=10)
        self.dpi_entry.grid(row=3, column=1, sticky="w", padx=2)

        # Label font size.
        self.label_font_var = tk.StringVar(value=str(self._settings.label_fontsize))
        ttk.Label(self, text="Label font").grid(row=4, column=0, sticky="e", padx=(8, 2))
        self.label_font_entry = ttk.Entry(self, textvariable=self.label_font_var, width=10)
        self.label_font_entry.grid(row=4, column=1, sticky="w", padx=2)

        # X / Y label-offset margins (inches).  Reserved whitespace around the
        # plot area so edge labels do not clip into the axes.
        self.x_offset_var = tk.StringVar(value=str(self._settings.x_offset))
        self.y_offset_var = tk.StringVar(value=str(self._settings.y_offset))
        ttk.Label(self, text="X offset (in)").grid(row=5, column=0, sticky="e", padx=(8, 2))
        self.x_offset_entry = ttk.Entry(self, textvariable=self.x_offset_var, width=10)
        self.x_offset_entry.grid(row=5, column=1, sticky="w", padx=2)
        ttk.Label(self, text="Y offset (in)").grid(row=6, column=0, sticky="e", padx=(8, 2))
        self.y_offset_entry = ttk.Entry(self, textvariable=self.y_offset_var, width=10)
        self.y_offset_entry.grid(row=6, column=1, sticky="w", padx=2)

        # Units dropdown.
        ttk.Label(self, text="Units").grid(row=7, column=0, sticky="e", padx=(8, 2))
        self.units_var = tk.StringVar(value=self._settings.units)
        self.units_combo = ttk.Combobox(
            self, textvariable=self.units_var, values=list(UNITS_CHOICES),
            state="readonly", width=9,
        )
        self.units_combo.grid(row=7, column=1, sticky="w", padx=2)

        # Format dropdown.
        ttk.Label(self, text="Format").grid(row=8, column=0, sticky="e", padx=(8, 2))
        self.format_var = tk.StringVar(value=self._settings.format)
        self.format_combo = ttk.Combobox(
            self, textvariable=self.format_var, values=list(FORMATS),
            state="readonly", width=9,
        )
        self.format_combo.grid(row=8, column=1, sticky="w", padx=2)

        self._sync_dim_enabled()

    def _sync_dim_enabled(self) -> None:
        state = "disabled" if self.dynamic_var.get() else "normal"
        for w in (self.width_entry, self.height_entry):
            w.configure(state=state)

    def to_settings(self, settings: GuiSettings | None = None) -> GuiSettings:
        from etabs_extractor.gui.state import parse_float, parse_int

        s = settings or GuiSettings()
        s.dynamic_size = bool(self.dynamic_var.get())
        s.fig_width = parse_float(self.width_var.get(), s.fig_width)
        s.fig_height = parse_float(self.height_var.get(), s.fig_height)
        s.dpi = parse_int(self.dpi_var.get(), s.dpi)
        s.label_fontsize = parse_float(self.label_font_var.get(), s.label_fontsize)
        s.x_offset = parse_float(self.x_offset_var.get(), s.x_offset)
        s.y_offset = parse_float(self.y_offset_var.get(), s.y_offset)
        s.units = self.units_var.get() if self.units_var.get() in UNITS_CHOICES else s.units
        s.format = self.format_var.get() if self.format_var.get() in FORMATS else s.format
        return s

    def from_settings(self, settings: GuiSettings) -> None:
        self.dynamic_var.set(settings.dynamic_size)
        self.width_var.set(str(settings.fig_width))
        self.height_var.set(str(settings.fig_height))
        self.dpi_var.set(str(settings.dpi))
        self.label_font_var.set(str(settings.label_fontsize))
        self.x_offset_var.set(str(settings.x_offset))
        self.y_offset_var.set(str(settings.y_offset))
        self.units_var.set(settings.units)
        self.format_var.set(settings.format)
        self._sync_dim_enabled()