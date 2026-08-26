#!/usr/bin/env python3
"""
beam_viewer.py — Interactive Beam Force Diagram Viewer

Loads frame-force CSV data extracted by etabs_extractor and displays
interactive axial-force (P), shear (V2), and bending-moment (M3) diagrams
for user-selected beams using matplotlib.

Controls:
  L / R arrows  — cycle load cases (left/right)
  U / D arrows  — cycle beams within the current section (up/down)
  S             — cycle through section types (B1, B2, K1, P600, RB-1)
  H             — toggle auto-select highest-force beam
  Q             — quit

Usage:
  python beam_viewer.py <path_to_all_forces.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── Force components to display ──────────────────────────────────────────
# (label, column, unit)
FORCE_DIAGRAMS = [
    ("Axial Force (P)", "P", "N"),
    ("Shear Force (V2)", "V2", "N"),
    ("Bending Moment (M3)", "M3", "N·mm"),
]


def load_data(csv_path: str) -> pd.DataFrame:
    """Load the all_forces CSV and return a filtered, sorted DataFrame."""
    df = pd.read_csv(csv_path)
    # Remove Modal results (they are not meaningful for force diagrams)
    df = df[df["load_name"] != "Modal"].copy()
    # Sort for consistent ordering
    df.sort_values(["load_name", "section", "frame", "station"], inplace=True)
    return df


def get_sections(df: pd.DataFrame) -> list[str]:
    """Return sorted unique section names."""
    return sorted(df["section"].unique())


def get_load_cases(df: pd.DataFrame) -> list[str]:
    """Return sorted unique load names."""
    return sorted(df["load_name"].unique())


def get_frames_for_section(df: pd.DataFrame, section: str) -> list[int]:
    """Return sorted unique frame numbers for a given section."""
    frames = df[df["section"] == section]["frame"].unique()
    return sorted(frames)


def get_beam_max_force(
    df: pd.DataFrame, section: str, load_name: str, force_col: str = "M3"
) -> tuple[int, float]:
    """Return (frame, max_abs_force) for the beam with highest |force|."""
    sub = df[(df["section"] == section) & (df["load_name"] == load_name)]
    if sub.empty:
        return (0, 0.0)
    idx = sub[force_col].abs().idxmax()
    row = sub.loc[idx]
    return (int(row["frame"]), row[force_col])


def get_lengths_for_section(df: pd.DataFrame, section: str) -> list[float]:
    """Return sorted unique beam lengths (mm) for a given section.

    Lengths are rounded to 1 mm precision to group floating-point
    noise from the COM extraction (e.g. 4099.999999998 → 4100.0).
    """
    sub = df[df["section"] == section]
    if "length_mm" not in sub.columns:
        return []
    lengths = sub["length_mm"].dropna().unique()
    # Round to 1 mm, then deduplicate
    rounded = sorted({round(l) for l in lengths})
    return rounded


def get_frames_for_length(
    df: pd.DataFrame, section: str, length_mm: float
) -> list[int]:
    """Return sorted frame numbers with a given section and length.

    Lengths are matched within 1 mm tolerance to handle floating-point
    noise from the COM extraction.
    """
    sub = df[df["section"] == section]
    if "length_mm" not in sub.columns:
        return []
    tol = 1.0  # mm
    mask = sub["length_mm"].notna() & (sub["length_mm"].sub(length_mm).abs() <= tol)
    frames = sub.loc[mask, "frame"].unique()
    return sorted(frames)


def get_beam_data(
    df: pd.DataFrame, frame: str | int, load_name: str
) -> pd.DataFrame | None:
    """Return the DataFrame for one frame + load, sorted by station.

    ``frame`` can be a string or int — the column is matched regardless
    of the DataFrame's dtype (int64 vs object).
    """
    frame_col = df["frame"]
    if frame_col.dtype.kind in ("i", "u", "f"):
        frame_val = int(frame)
    else:
        frame_val = str(frame)
    sub = df[(frame_col == frame_val) & (df["load_name"] == load_name)].copy()
    if sub.empty:
        return None
    # Sort by step_type then station — groups envelope steps (Max, Min)
    # into contiguous runs so each step plots as a clean line.
    sub.sort_values(["step_type", "station"], inplace=True)
    sub.reset_index(drop=True, inplace=True)
    return sub


def get_force_groups(
    beam_data: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Split beam data by step_type.

    Non-envelope loads (empty/single step) return one group under key ``""``.
    Envelope combos return one group per step type (``"Max"``, ``"Min"``).
    Each group is sorted by station.
    """
    groups: dict[str, pd.DataFrame] = {}
    for step, grp in beam_data.groupby("step_type", sort=False):
        grp = grp.sort_values("station").reset_index(drop=True)
        groups[str(step) if step else ""] = grp
    return groups


def get_beam_step_types(
    df: pd.DataFrame, frame: str | int, load_name: str
) -> list[str]:
    """Return the distinct step types for a given frame + load.

    Returns ``["Max", "Min"]`` for envelope combos, ``[""]`` (single
    empty string) for plain loads, or an empty list if no data.
    """
    beam_data = get_beam_data(df, frame, load_name)
    if beam_data is None or beam_data.empty:
        return []
    return list(get_force_groups(beam_data).keys())


def _scale_force(val: float, col: str) -> float:
    """Convert force values: N → kN, N·mm → kN·m for display."""
    if col in ("P", "V2", "V3"):
        return val / 1000.0
    if col in ("M2", "M3", "T"):
        return val / 1e6
    return val


def _unit_label(col: str) -> str:
    """Return the display unit label for a force column."""
    if col in ("P", "V2", "V3"):
        return "kN"
    if col in ("M2", "M3", "T"):
        return "kN·m"
    return ""


def _diagram_vals(vals: np.ndarray, col: str) -> np.ndarray:
    """Return display values and fill signs for the given column.

    For moment diagrams (M2, M3), values are **negated** so that
    positive moment (sagging, tension at bottom) plots BELOW the
    zero line, matching structural engineering convention.
    """
    if col in ("M2", "M3"):
        return -vals
    return vals


def plot_beam_diagrams(
    beam_data: pd.DataFrame,
    frame: int | str,
    load_name: str,
    section: str,
    axs: list,
    force_cols: tuple = ("P", "V2", "M3"),
    step_type: str | None = None,
) -> None:
    """Plot the force diagrams for one beam on the given axes.

    Parameters
    ----------
    step_type : str or None
        ``"Max"`` or ``"Min"`` to show only that envelope step, or
        ``None`` to show all steps overlaid.  For non-envelope loads
        this is ignored and a single blue line is drawn.

    Moment diagrams (M3) are inverted so positive moment (sagging) plots
    BELOW the zero line, matching structural engineering convention.
    """
    groups = get_force_groups(beam_data)

    length_mm = (
        beam_data["length_mm"].iloc[0]
        if "length_mm" in beam_data.columns
        else beam_data["station"].max()
    )
    length_m = length_mm / 1000.0 if length_mm else 0.0

    is_envelope = len(groups) > 1

    for ax, col in zip(axs, force_cols):
        ax.clear()
        label = _unit_label(col)
        col_name = {"P": "Axial (P)", "V2": "Shear (V2)", "M3": "Moment (M3)"}.get(col, col)
        # Moment diagrams: positive plots below, so swap fill colors too
        _pos_fill = "red" if col in ("M2", "M3") else "green"
        _neg_fill = "green" if col in ("M2", "M3") else "red"

        all_v = np.array([])
        all_s = np.array([])

        def _make_vals(grp):
            raw = np.array([_scale_force(v, col) for v in grp[col].values])
            return _diagram_vals(raw, col)

        if is_envelope and step_type:
            # Single step: plot only the requested step
            if step_type in groups:
                grp = groups[step_type]
                stations_m = grp["station"].values / 1000.0
                vals = _make_vals(grp)
                all_s, all_v = stations_m, vals
                ax.plot(stations_m, vals, color="blue", linewidth=2.0,
                        marker="o", markersize=4, label=step_type)
                ax.fill_between(stations_m, vals, 0,
                    where=(vals >= 0), color=_pos_fill, alpha=0.1,
                )
                ax.fill_between(stations_m, vals, 0,
                    where=(vals < 0), color=_neg_fill, alpha=0.1,
                )
                ax.legend(loc="upper right", fontsize=8)
        elif is_envelope:
            # Both steps: plot Max (red) and Min (blue) overlaid
            step_styles = [
                ("Max", "red", "Max"),
                ("Min", "blue", "Min"),
            ]
            for step_key, color, legend_label in step_styles:
                if step_key not in groups:
                    continue
                grp = groups[step_key]
                stations_m = grp["station"].values / 1000.0
                vals = _make_vals(grp)
                if len(vals) == 0:
                    continue
                all_s = np.concatenate([all_s, stations_m])
                all_v = np.concatenate([all_v, vals])
                ax.plot(stations_m, vals, color=color, linewidth=2.0,
                        marker="o", markersize=4, label=legend_label)
                ax.fill_between(stations_m, vals, 0,
                    where=(vals >= 0), color=_pos_fill, alpha=0.06,
                )
                ax.fill_between(stations_m, vals, 0,
                    where=(vals < 0), color=_neg_fill, alpha=0.06,
                )
            if any(k in groups for k in ("Max", "Min")):
                ax.legend(loc="upper right", fontsize=8)
        else:
            # Single step: one clean blue line
            grp = next(iter(groups.values()))
            stations_m = grp["station"].values / 1000.0
            vals = _make_vals(grp)
            all_s, all_v = stations_m, vals
            ax.plot(stations_m, vals, color="blue", linewidth=2.0,
                    marker="o", markersize=4)
            ax.fill_between(stations_m, vals, 0,
                where=(vals >= 0), color=_pos_fill, alpha=0.1,
            )
            ax.fill_between(stations_m, vals, 0,
                where=(vals < 0), color=_neg_fill, alpha=0.1,
            )

        # Zero line
        ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")

        ax.set_ylabel(f"{col_name} [{label}]", fontsize=10)
        ax.set_xlabel("Position along beam [m]", fontsize=10)
        ax.grid(True, alpha=0.3)

        # Invert Y-axis tick labels for moment diagrams so they show
        # the original signed moment, not the negated plot coordinate.
        if col in ("M2", "M3"):
            def _moment_fmt(x, _pos, _col=col):
                return f"{_diagram_vals(np.array([x]), _col)[0]:.0f}"
            ax.yaxis.set_major_formatter(plt.FuncFormatter(_moment_fmt))

        # Annotate global max/min (undo diagram inversion so values show
        # the original signed moment, not the negated plot coordinate)
        if len(all_v) > 0:
            max_idx = np.argmax(all_v)
            min_idx = np.argmin(all_v)
            # Reverse negation for annotation display values
            _ann_max = _diagram_vals(all_v[max_idx:max_idx+1], col)[0]
            _ann_min = _diagram_vals(all_v[min_idx:min_idx+1], col)[0]
            ax.annotate(
                f"Max: {_ann_max:.1f}",
                xy=(all_s[max_idx], all_v[max_idx]),
                xytext=(5, 10), textcoords="offset points",
                fontsize=7, color="green", fontweight="bold",
            )
            ax.annotate(
                f"Min: {_ann_min:.1f}",
                xy=(all_s[min_idx], all_v[min_idx]),
                xytext=(5, -15), textcoords="offset points",
                fontsize=7, color="red", fontweight="bold",
            )

    # Common x-range
    for ax in axs:
        ax.set_xlim(0, length_m * 1.05)

    # Title
    step_label = step_type if step_type else ("Both" if is_envelope else "")
    step_info = f" | Step: {step_label}" if step_label else ""
    axs[0].set_title(
        f"Beam {frame}  |  Section: {section}  |  Load: {load_name}  |  "
        f"L={length_m:.2f}m{step_info}",
        fontsize=12, fontweight="bold",
    )


def build_frame_figure(
    df: pd.DataFrame,
    frame: int | str,
    load_name: str,
    section: str | None = None,
    *,
    figsize: tuple[float, float] = (12, 10),
    step_type: str | None = None,
) -> plt.Figure | None:
    """Build a 3-panel beam force diagram figure (P, V2, M3).

    Filters ``df`` by ``frame`` and ``load_name``, optionally overrides
    the section label.  ``step_type`` limits to one envelope step
    (``"Max"`` / ``"Min"``, or ``None`` for all steps).
    Returns the Figure (or ``None`` if no data found).
    The caller is responsible for closing it when done.
    """
    beam_data = get_beam_data(df, frame, load_name)
    if beam_data is None or beam_data.empty:
        return None
    sec_name = section or beam_data["section"].iloc[0]
    fig, axs = plt.subplots(3, 1, figsize=figsize, sharex=True)
    fig.subplots_adjust(hspace=0.35, left=0.08, right=0.95, top=0.94, bottom=0.06)
    plot_beam_diagrams(beam_data, frame, load_name, sec_name, axs, step_type=step_type)
    return fig


class BeamViewer:
    """Interactive beam force diagram viewer."""

    def __init__(self, csv_path: str) -> None:
        self.df = load_data(csv_path)
        self.sections = get_sections(self.df)
        self.load_cases = get_load_cases(self.df)

        # State
        self.section_idx = 0
        self.load_idx = 0
        self.auto_select = True  # Auto-select highest-force beam

        # Pre-compute section+load → frame list
        self._update_frame_list()

        # Select initial beam
        self._select_beam()

        # Build figure
        self.fig, self.axs = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        self.fig.canvas.manager.set_window_title("Beam Force Diagram Viewer")
        self.fig.subplots_adjust(hspace=0.35, left=0.08, right=0.95, top=0.94, bottom=0.06)

        # Connect keyboard events
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        # Render
        self._render()

        # Display status bar info
        self._update_status()

        plt.show()

    def _update_frame_list(self) -> None:
        section = self.sections[self.section_idx]
        self.frames = get_frames_for_section(self.df, section)

    def _select_beam(self) -> None:
        section = self.sections[self.section_idx]
        load = self.load_cases[self.load_idx]

        if self.auto_select:
            frame, _ = get_beam_max_force(self.df, section, load, "M3")
            if frame == 0 and self.frames:
                frame = self.frames[0]
        else:
            frame = self.frames[0] if self.frames else 0

        self.frame_idx = 0
        if frame in self.frames:
            self.frame_idx = self.frames.index(frame)
        elif self.frames:
            self.frame_idx = 0

    def _get_beam_section_info(self, frame: int) -> str:
        """Get section info for a frame."""
        sub = self.df[self.df["frame"] == frame]
        if not sub.empty:
            return sub["section"].iloc[0]
        return ""

    def _render(self) -> None:
        section = self.sections[self.section_idx]
        load = self.load_cases[self.load_idx]

        if not self.frames:
            for ax in self.axs:
                ax.clear()
                ax.text(0.5, 0.5, "No beams in this section", transform=ax.transAxes, ha="center")
            self.fig.canvas.draw_idle()
            return

        frame = self.frames[self.frame_idx]
        beam_data = get_beam_data(self.df, frame, load)

        if beam_data is None or beam_data.empty:
            for ax in self.axs:
                ax.clear()
                ax.text(0.5, 0.5, "No data for this beam/load", transform=ax.transAxes, ha="center")
            self.fig.canvas.draw_idle()
            return

        sec_name = self._get_beam_section_info(frame)
        plot_beam_diagrams(beam_data, frame, load, sec_name, self.axs)
        self.fig.canvas.draw_idle()

    def _update_status(self) -> None:
        section = self.sections[self.section_idx]
        load = self.load_cases[self.load_idx]
        frame = self.frames[self.frame_idx] if self.frames else 0
        n_frames = len(self.frames)

        status = (
            f"Section: {section} ({self.section_idx + 1}/{len(self.sections)}) | "
            f"Load: {load} ({self.load_idx + 1}/{len(self.load_cases)}) | "
            f"Beam: {frame} ({self.frame_idx + 1}/{n_frames}) | "
            f"Auto: {'ON' if self.auto_select else 'OFF'} | "
            "S:section  ←→:load  ↑↓:beam  H:auto  Q:quit"
        )
        self.fig.suptitle(status, fontsize=9, y=0.98)
        self.fig.canvas.draw_idle()

    def _on_key(self, event) -> None:
        if event.key == "q":
            plt.close(self.fig)
            return

        if event.key == "s":
            # Cycle section
            self.section_idx = (self.section_idx + 1) % len(self.sections)
            self._update_frame_list()
            self._select_beam()
            self._render()
            self._update_status()
            return

        if event.key == "h":
            self.auto_select = not self.auto_select
            if self.auto_select:
                self._select_beam()
            self._render()
            self._update_status()
            return

        if event.key == "left":
            self.load_idx = (self.load_idx - 1) % len(self.load_cases)
            self._select_beam()
            self._render()
            self._update_status()
            return

        if event.key == "right":
            self.load_idx = (self.load_idx + 1) % len(self.load_cases)
            self._select_beam()
            self._render()
            self._update_status()
            return

        if event.key == "up":
            if self.frames:
                self.frame_idx = (self.frame_idx + 1) % len(self.frames)
                self.auto_select = False
                self._render()
                self._update_status()
            return

        if event.key == "down":
            if self.frames:
                self.frame_idx = (self.frame_idx - 1) % len(self.frames)
                self.auto_select = False
                self._render()
                self._update_status()
            return


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python beam_viewer.py <path_to_all_forces.csv>", file=sys.stderr)
        print()
        print("Example:")
        print("  python beam_viewer.py /mnt/d/.../extracted/all_forces.csv", file=sys.stderr)
        sys.exit(1)

    csv_path = sys.argv[1]
    if not Path(csv_path).exists():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print("Loading data...")
    print("Controls:")
    print("  ← →  : cycle load cases")
    print("  ↑ ↓  : cycle beams")
    print("  S    : cycle section type")
    print("  H    : toggle auto-select highest-force beam")
    print("  Q    : quit")
    print()

    BeamViewer(csv_path)


if __name__ == "__main__":
    main()