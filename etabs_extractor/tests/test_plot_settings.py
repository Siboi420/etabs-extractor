"""Headless unit tests for the GUI's pure, testable layers.

Covers:
* ``plots.build_base_reactions_figure`` — the reusable figure builder
  (returns a Figure with the requested size when ``dynamic_size=False``; a
  data-derived size when ``dynamic_size=True``; ``None`` when there are no
  plottable points).
* ``plots.plot_base_reactions`` — dpi / dynamic_size / figsize /
  label_fontsize threading (writes non-empty files; dpi passed to savefig).
* ``gui.service`` — settings->library-args mapping (pure, no display).
* ``gui.state`` — combo/elevation parsing helpers.

These run headlessly (MPLBACKEND=Agg) in WSL with NO display and NO comtypes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

# Make the package importable when run directly as a script.
import sys

if __package__ in (None, ""):
    # Test lives at <root>/etabs_extractor/tests/, so go up 3 levels to root.
    sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)

import pandas as pd

from etabs_extractor.gui import service
from etabs_extractor.gui.state import (
    GuiSettings,
    LoadSelectionModel,
    parse_combos,
    parse_elevation,
)
from etabs_extractor.plots import (
    build_base_reactions_figure,
    plot_base_reactions,
)


def _sample_df():
    """Small synthetic base-reaction frame with two points and one load."""
    return pd.DataFrame(
        [
            {"point": "1", "x": 0.0, "y": 0.0, "z": 0.0,
             "load_name": "ASD 1", "load_kind": "COMBO",
             "F1": 10.0, "F2": 2.0, "F3": 120.0, "M1": 1.0, "M2": 3.0, "M3": 0.5},
            {"point": "2", "x": 6000.0, "y": 0.0, "z": 0.0,
             "load_name": "ASD 1", "load_kind": "COMBO",
             "F1": -8.0, "F2": -1.0, "F3": 110.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
        ]
    )


def _envelope_df():
    """Synthetic two-load frame: one envelope load with Max/Min rows whose
    governing values differ per point, plus one stepless (plain case) load."""
    rows = []
    for step, f3_p1, f3_p2 in (("Max", 100.0, -30.0), ("Min", -60.0, -80.0)):
        rows.append(
            {"point": "1", "x": 0.0, "y": 0.0, "z": 0.0,
             "load_name": "ENV", "load_kind": "COMBO", "step_type": step,
             "F1": 10.0, "F2": 2.0, "F3": f3_p1, "M1": 1.0, "M2": 3.0, "M3": 0.5},
        )
        rows.append(
            {"point": "2", "x": 6000.0, "y": 0.0, "z": 0.0,
             "load_name": "ENV", "load_kind": "COMBO", "step_type": step,
             "F1": -8.0, "F2": -1.0, "F3": f3_p2, "M1": 0.0, "M2": 0.0, "M3": 0.0},
        )
    # Stepless load (plain case / legacy CSV: no step_type column rows).
    rows.append(
        {"point": "1", "x": 0.0, "y": 0.0, "z": 0.0,
         "load_name": "DL", "load_kind": "CASE",
         "F1": 1.0, "F2": 0.0, "F3": 50.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
    )
    return pd.DataFrame(rows)


def _no_point_df():
    """A frame with only NaN coordinates (no plottable points)."""
    return pd.DataFrame(
        [
            {"point": "x", "x": None, "y": None, "z": None,
             "load_name": "NONE", "load_kind": "COMBO",
             "F1": 0.0, "F2": 0.0, "F3": 0.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
        ]
    )


def _corner_df():
    """A four-corner frame with distinct x **and** y, so axis-limit padding
    is observable in both directions (the 2-point sample is x-only)."""
    return pd.DataFrame(
        [
            {"point": "1", "x": 0.0, "y": 0.0, "z": 0.0,
             "load_name": "ASD 1", "load_kind": "COMBO",
             "F1": 10.0, "F2": 2.0, "F3": 120.0, "M1": 1.0, "M2": 3.0, "M3": 0.5},
            {"point": "2", "x": 6000.0, "y": 0.0, "z": 0.0,
             "load_name": "ASD 1", "load_kind": "COMBO",
             "F1": -8.0, "F2": -1.0, "F3": 110.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
            {"point": "3", "x": 0.0, "y": 4000.0, "z": 0.0,
             "load_name": "ASD 1", "load_kind": "COMBO",
             "F1": 5.0, "F2": 0.0, "F3": 130.0, "M1": 0.0, "M2": 1.0, "M3": 2.0},
            {"point": "4", "x": 6000.0, "y": 4000.0, "z": 0.0,
             "load_name": "ASD 1", "load_kind": "COMBO",
             "F1": -3.0, "F2": 0.0, "F3": 140.0, "M1": 0.0, "M2": 0.0, "M3": 1.0},
        ]
    )


def test_gui_imports_without_display():
    """Importing the GUI package/state/service must succeed with no display."""
    import etabs_extractor.gui.app
    import etabs_extractor.gui.runner
    import etabs_extractor.gui.widgets.plot_settings
    import etabs_extractor.gui.widgets.preview  # noqa: F401
    print("GUI import OK (no display, no comtypes)")


def test_build_figure_fixed_size():
    df = _sample_df()
    # Offsets no longer change the canvas: the figure is exactly the base
    # size; the offsets are applied to the axis limits instead.
    fig = build_base_reactions_figure(
        df, "ASD 1",
        dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=1, y_offset=1,
    )
    assert fig is not None, "expected a Figure for plottable data"
    w, h = fig.get_size_inches()
    assert abs(w - 12.0) < 1e-6 and abs(h - 6.0) < 1e-6, (w, h)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("build_base_reactions_figure fixed figsize OK (canvas unchanged)")


def test_offsets_expand_axis_limits_not_canvas():
    """X/Y offsets widen the axis limits (labels stay inside the box) while
    the canvas stays exactly the base size."""
    df = _corner_df()
    unpadded = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=0, y_offset=0,
    )
    padded = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=1.5, y_offset=0.5,
    )
    assert unpadded is not None and padded is not None
    # Same canvas: offsets change limits, never the figure size.
    pw, ph = padded.get_size_inches()
    uw, uh = unpadded.get_size_inches()
    assert pw == uw == 12.0 and ph == uh == 6.0, (pw, ph, uw, uh)
    bx0, bx1 = unpadded.axes[0].get_xlim()
    by0, by1 = unpadded.axes[0].get_ylim()
    px0, px1 = padded.axes[0].get_xlim()
    py0, py1 = padded.axes[0].get_ylim()
    # Limits strictly wider on every side.
    assert px0 < bx0 and px1 > bx1, (bx0, bx1, px0, px1)
    assert py0 < by0 and py1 > by1, (by0, by1, py0, py1)
    import matplotlib.pyplot as plt
    plt.close(padded)
    plt.close(unpadded)
    print("offsets expand axis limits (canvas unchanged) OK")


def test_build_figure_zero_offset_reproduces_base():
    """Offsets of 0 leave both the canvas and the limits at their base values."""
    df = _corner_df()
    fig = build_base_reactions_figure(
        df, "ASD 1",
        dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=0, y_offset=0,
    )
    assert fig is not None
    w, h = fig.get_size_inches()
    assert abs(w - 12.0) < 1e-6 and abs(h - 6.0) < 1e-6, (w, h)
    ref = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=0, y_offset=0,
    )
    assert ref is not None
    assert fig.axes[0].get_xlim() == ref.axes[0].get_xlim()
    assert fig.axes[0].get_ylim() == ref.axes[0].get_ylim()
    import matplotlib.pyplot as plt
    plt.close(fig)
    plt.close(ref)
    print("build_base_reactions_figure zero offsets -> base limits OK")


def test_plot_base_reactions_offset_threading():
    """Offsets thread through to the built figure; writes a non-empty PNG with
    no edge-label clipping exception."""
    df = _corner_df()
    with tempfile.TemporaryDirectory() as td:
        paths = plot_base_reactions(
            df, td, dpi=100, dynamic_size=False, figsize=(12, 6),
            label_fontsize=5, load_name="ASD 1",
            x_offset=1.5, y_offset=0.5,
        )
        assert len(paths) == 1, paths
        p = paths[0]
        assert p.exists() and p.stat().st_size > 0, p
        # Rebuild via the public figure builder: the canvas is the fixed base
        # and the offsets only widen the limits.
        fig = build_base_reactions_figure(
            df, "ASD 1", dynamic_size=False, figsize=(12, 6),
            x_offset=1.5, y_offset=0.5,
        )
        assert fig is not None
        w, h = fig.get_size_inches()
        assert abs(w - 12.0) < 1e-6 and abs(h - 6.0) < 1e-6, (w, h)
        import matplotlib.pyplot as plt
        plt.close(fig)
        print("plot_base_reactions offsets threaded OK")


def test_build_figure_dynamic_size():
    df = _sample_df()
    fig = build_base_reactions_figure(df, "ASD 1", dynamic_size=True)
    assert fig is not None
    w, h = fig.get_size_inches()
    # Dynamic base canvas (>= 6x5 min); offsets no longer inflate it.
    assert w >= 6.0 and h >= 5.0, (w, h)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("build_base_reactions_figure dynamic size OK")


def test_build_figure_dynamic_offset_limits():
    """Dynamic mode: offsets widen the limits while the canvas equals the
    dynamic base (offsets never inflate the figure)."""
    df = _corner_df()
    padded = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=True, x_offset=1.5, y_offset=0.5,
    )
    assert padded is not None
    w, h = padded.get_size_inches()
    assert w >= 6.0 and h >= 5.0, (w, h)
    unpadded = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=True, x_offset=0, y_offset=0,
    )
    assert unpadded is not None
    # Same dynamic canvas in both runs.
    assert all(padded.get_size_inches() == unpadded.get_size_inches())
    bx0, bx1 = unpadded.axes[0].get_xlim()
    by0, by1 = unpadded.axes[0].get_ylim()
    px0, px1 = padded.axes[0].get_xlim()
    py0, py1 = padded.axes[0].get_ylim()
    assert px0 < bx0 and px1 > bx1, (bx0, bx1, px0, px1)
    assert py0 < by0 and py1 > by1, (by0, by1, py0, py1)
    import matplotlib.pyplot as plt
    plt.close(padded)
    plt.close(unpadded)
    print("build_base_reactions_figure dynamic offsets -> limits OK")


def test_build_figure_none_for_no_points():
    fig = build_base_reactions_figure(_no_point_df(), "NONE")
    assert fig is None, "expected None when there are no plottable points"
    print("build_base_reactions_figure no-points -> None OK")


def test_plot_base_reactions_dpi_figsize():
    df = _sample_df()
    with tempfile.TemporaryDirectory() as td:
        paths = plot_base_reactions(
            df, td,
            dpi=100, dynamic_size=False, figsize=(12, 6), label_fontsize=5,
            load_name="ASD 1",
        )
        assert len(paths) == 1, paths
        # dpi is passed to savefig via keyword; assert simply that files are
        # written and non-empty.
        p = paths[0]
        assert p.exists() and p.stat().st_size > 0, p
        print("plot_base_reactions dpi/figsize/fontsize OK")


def test_service_frame_mode_kwargs():
    """Frame-mode settings map to extract_forces kwargs (frames + sections,
    no elevation/only_loaded); base mode is unchanged."""
    s = GuiSettings(
        model_path="/mnt/d/models/x.EDB", output_dir="/mnt/d/out", tag="K",
        extract_mode="frame",
        selected_combos=["ASD 1"], selected_cases=["Dead"],
        selected_sections=["COL1"], selected_frames=["C1"],
    )
    kw = service.build_extract_kwargs(s)
    assert kw["sections"] == ["COL1"]
    assert kw["frames"] == ["C1"]
    assert kw["combos"] == ["ASD 1"]
    assert kw["cases"] == ["Dead"]
    # No base-only kwargs in frame mode.
    assert "elevation" not in kw
    assert "only_loaded" not in kw
    # Unit kwargs default to "model" and thread through in frame mode too.
    assert kw["force_unit"] == "model"
    assert kw["length_unit"] == "model"
    # Empty sections/frames -> None (no filter).
    s2 = GuiSettings(extract_mode="frame")
    kw2 = service.build_extract_kwargs(s2)
    assert kw2["sections"] is None and kw2["frames"] is None
    print("service.build_extract_kwargs (frame mode) OK")


def test_load_selection_model_kind_groups():
    """LoadSelectionModel generalised to configurable group kinds (sections /
    frames); ``get_selected`` returns the two groups."""
    model = LoadSelectionModel(kind_a="section", kind_b="frame")
    model.set_items(["COL1", "B1"], ["C1", "B2"])
    assert model.all_combos == ["COL1", "B1"]
    assert model.all_cases == ["C1", "B2"]
    items = model.items()
    model.toggle(items.index(next(i for i in items if i.name == "COL1")), True)
    model.toggle(items.index(next(i for i in items if i.name == "B2")), True)
    a, b = model.get_selected()
    assert a == ["COL1"], a
    assert b == ["B2"], b
    print("LoadSelectionModel frame kinds OK")


def test_inspect_active_model_fake2():
    """inspect_active_model returns sections/frames from the fake, and
    degrades to [] when the fake lacks those methods (best-effort)."""
    class _Full:
        def get_model_filename(self, include_path=True):
            return "D:\\Models\\fake.EDB"
        def get_combo_names(self):
            return ["ASD 1"]
        def get_case_names(self):
            return ["Dead"]
        def get_frame_section_names(self):
            return ["COL1", "B1"]
        def get_frame_names(self):
            return ["C1", "B1"]

    info = service.inspect_active_model(attach=False, session=_Full())
    assert info["sections"] == ["COL1", "B1"]
    assert info["frames"] == ["C1", "B1"]

    class _Sparse:
        def get_model_filename(self, include_path=True):
            return "D:\\Models\\fake.EDB"
        def get_combo_names(self):
            return []
        def get_case_names(self):
            return []

    info2 = service.inspect_active_model(attach=False, session=_Sparse())
    assert info2["sections"] == [] and info2["frames"] == []
    print("inspect_active_model sections/frames OK")


def test_service_extract_kwargs_mapping():
    s = GuiSettings(
        model_path="/mnt/d/models/x.EDB",
        output_dir="/mnt/d/out",
        tag="KM13",
        selected_combos=["ASD 1", "LRFD 1"],
        selected_cases=["Dead"],
        elevation="-16000",
        only_loaded=True,
        run_analysis=False,
        attach=True,
        force_unit="kN",
        length_unit="m",
    )
    kw = service.build_extract_kwargs(s)
    assert kw["model_path"] == "/mnt/d/models/x.EDB"
    assert kw["output_dir"] == "/mnt/d/out"
    assert kw["combos"] == ["ASD 1", "LRFD 1"]
    assert kw["cases"] == ["Dead"]
    assert kw["elevation"] == -16000.0
    assert kw["only_loaded"] is True
    assert kw["attach"] is True
    assert kw["launch"] is False
    assert kw["tag"] == "KM13"
    assert kw["force_unit"] == "kN"
    assert kw["length_unit"] == "m"
    # Empty selection -> both None (all model combos default).
    s2 = GuiSettings()
    kw2 = service.build_extract_kwargs(s2)
    assert kw2["combos"] is None
    assert kw2["cases"] is None
    assert kw2["force_unit"] == "model"
    assert kw2["length_unit"] == "model"
    print("service.build_extract_kwargs OK")


def test_load_selection_model():
    """LoadSelectionModel filtering + split selection retrieval."""
    model = LoadSelectionModel(combos=["ASD 1", "LRFD Max"], cases=["Dead", "Live"])
    assert model.all_combos == ["ASD 1", "LRFD Max"]
    assert model.all_cases == ["Dead", "Live"]
    # Substring filter matches across both kinds (case-insensitive).
    matched = model.matches("asd")
    assert [it.name for it in matched] == ["ASD 1"], matched
    matched2 = model.matches("1")
    assert {it.name for it in matched2} == {"ASD 1"}, matched2
    matched3 = model.matches("dead")
    assert [it.name for it in matched3] == ["Dead"], matched3
    # Empty query returns all items.
    assert len(model.matches("")) == 4
    # Toggle selection and retrieve as split (combos, cases).
    items = model.items()
    model.toggle(items.index(next(i for i in items if i.name == "ASD 1")), True)
    model.toggle(items.index(next(i for i in items if i.name == "Dead")), True)
    combos, cases = model.get_selected()
    assert combos == ["ASD 1"], combos
    assert cases == ["Dead"], cases
    # Selection persists across a filter round-trip.
    assert model.matches("")[0].selected is True
    print("LoadSelectionModel OK")


def test_inspect_active_model_fake():
    """inspect_active_model with an injected fake session returns model path +
    combos + cases."""
    class _Fake:
        def get_model_filename(self, include_path=True):
            return "D:\\Models\\fake.EDB"
        def get_combo_names(self):
            return ["ASD 1", "LRFD 1"]
        def get_case_names(self):
            return ["Dead", "Live"]

    info = service.inspect_active_model(attach=False, session=_Fake())
    assert info["model_path"] == "D:\\Models\\fake.EDB"
    assert info["combos"] == ["ASD 1", "LRFD 1"]
    assert info["cases"] == ["Dead", "Live"]
    # The richer call drives check_active_model bag to the same path.
    assert service.check_active_model(attach=False, session=_Fake()).startswith("D:\\")
    print("inspect_active_model (fake) OK")


def test_build_figure_label_offsets():
    """label_dx/label_dy become the annotation's offset-points position;
    defaults reproduce the historical (-6, -18)."""
    df = _sample_df()
    fig = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6),
        label_dx=10, label_dy=0,
    )
    assert fig is not None
    for ann in fig.axes[0].texts:
        # get_position() == the offset-points tuple (Annotation.xyann) for
        # textcoords="offset points".
        assert ann.get_position() == (10.0, 0.0), ann.get_position()
    import matplotlib.pyplot as plt
    plt.close(fig)
    default = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6),
    )
    assert default is not None
    for ann in default.axes[0].texts:
        assert ann.get_position() == (-6.0, -18.0), ann.get_position()
    plt.close(default)
    print("build_base_reactions_figure label offsets OK")


def test_build_figure_label_components():
    """components selects the label's value lines; empty -> point number only."""
    df = _sample_df()
    fig = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6), components=("Fz", "Fx"),
    )
    assert fig is not None
    for ann in fig.axes[0].texts:
        assert "Fx=" in ann.get_text(), ann.get_text()
        assert "Fz=" in ann.get_text(), ann.get_text()
        assert "M2=" not in ann.get_text(), ann.get_text()
    import matplotlib.pyplot as plt
    plt.close(fig)
    default = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6),
    )
    assert default is not None
    for ann in default.axes[0].texts:
        assert "Fx=" not in ann.get_text(), ann.get_text()
        assert "Fz=" in ann.get_text(), ann.get_text()
    plt.close(default)
    empty = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=False, figsize=(12, 6), components=(),
    )
    assert empty is not None
    for ann in empty.axes[0].texts:
        assert ann.get_text().strip() in {"1", "2"}, ann.get_text()
    plt.close(empty)
    print("build_base_reactions_figure label components OK")


def test_plot_base_reactions_label_kwargs():
    """label_dx/label_dy/components thread through plot_base_reactions (incl.
    a steps variant) and write non-empty files."""
    df = _envelope_df()
    with tempfile.TemporaryDirectory() as td:
        paths = plot_base_reactions(
            df, td, dpi=100, dynamic_size=False, figsize=(12, 6),
            label_dx=8, label_dy=-4, components=("Fz",),
            steps=("absmax", "max"),
        )
        paths = [p for p in paths if str(p)]
        assert paths, paths
        for p in paths:
            assert p.exists() and p.stat().st_size > 0, p
    print("plot_base_reactions label kwargs threaded OK")


def test_service_label_kwargs_and_csv_filter():
    """build_plot_kwargs / build_figure_kwargs expose the three new keys in
    canonical component order, and the CSV plot path's key filter passes
    them through (end-to-end: writes non-empty files)."""
    s = GuiSettings(label_dx=5.0, label_dy=-2.5,
                    label_components=["M2", "Fz"])
    kw = service.build_plot_kwargs(s)
    assert kw["label_dx"] == 5.0
    assert kw["label_dy"] == -2.5
    assert kw["components"] == ("Fz", "M2")  # canonical order
    fk = service.build_figure_kwargs(s)
    assert fk["label_dx"] == 5.0
    assert fk["label_dy"] == -2.5
    assert fk["components"] == ("Fz", "M2")
    # Deselect-all -> empty tuple (point-number-only labels).
    assert service.build_plot_kwargs(GuiSettings(label_components=[]))["components"] == ()
    # End-to-end CSV path: build a temp CSV and load_from_csv with plotting.
    df = _sample_df()
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "all_base_reactions.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8")
        s2 = GuiSettings(csv_path=str(csv_path), plot_after_extract=True,
                         label_dx=8.0, label_dy=0.0,
                         label_components=["Fz"])
        result = service.load_from_csv(s2)
        assert result["plot_paths"], result["plot_paths"]
        for p in result["plot_paths"]:
            assert p.exists() and p.stat().st_size > 0, p
    print("service label kwargs + CSV filter passthrough OK")


def test_service_plot_kwargs_mapping():
    s = GuiSettings(dynamic_size=False, fig_width=12.0, fig_height=6.0,
                    dpi=300, label_fontsize=3, units="kN-m", format="svg",
                    tag="x")
    kw = service.build_plot_kwargs(s)
    assert kw["dynamic_size"] is False
    assert kw["figsize"] == (12.0, 6.0)
    assert kw["dpi"] == 300
    assert kw["label_fontsize"] == 3
    assert kw["units"] == "kN-m"
    assert kw["fmt"] == "svg"
    assert kw["tag"] == "x"
    assert kw["x_offset"] == 1.0
    assert kw["y_offset"] == 1.0
    # Dynamic (default) -> figsize is None.
    s2 = GuiSettings(dynamic_size=True)
    kw2 = service.build_plot_kwargs(s2)
    assert kw2["dynamic_size"] is True
    assert kw2["figsize"] is None
    print("service.build_plot_kwargs OK")


def test_state_parsing():
    assert parse_combos("ASD 1, LRFD 1") == ["ASD 1", "LRFD 1"]
    assert parse_combos("  ") == []
    assert parse_combos("") == []
    # Commas separate; names may themselves contain spaces.
    assert parse_combos("A B, C") == ["A B", "C"]
    assert parse_elevation("") is None
    assert parse_elevation("-16000") == -16000.0
    # The elevation combobox's labelled entries (see app._refresh_elevation_
    # choices) must still parse: leading numeric token, trailing "(...)"
    # label ignored.
    assert parse_elevation("-18.55  (Base, 42 pts)") == -18.55
    assert parse_elevation("1900  (+ 1.90, 60 pts)") == 1900.0
    try:
        parse_elevation("not-a-number")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        # Expected: raise the value through to assert the error propagated.
        assert "Invalid elevation" in str(exc)
        print(f"state parsing OK (rejected {str(exc)!r})")


def test_plot_single_step_stem_and_title():
    """A single-step frame (like a MIN/MAX split CSV) plots under a
    step-suffixed filename and a step-augmented title; multi-step or
    stepless frames keep legacy names."""
    from etabs_extractor.plots import _build_title, _single_step

    df = _sample_df()
    df["step_type"] = "Min"
    assert _single_step(df) == "Min"
    title = _build_title(df, "ASD 1", {"length": "mm", "length_scale": 1.0})
    assert "ASD 1 (Min)" in title, title
    # Multi-step -> no single step (legacy naming).
    df2 = _sample_df()
    df2["step_type"] = ["Max", "Min"]
    assert _single_step(df2) is None
    # No step column -> None.
    df3 = _sample_df()
    assert _single_step(df3) is None
    with tempfile.TemporaryDirectory() as td:
        paths = plot_base_reactions(
            df, td, dpi=100, dynamic_size=False, figsize=(6, 6),
            load_name="ASD 1",
        )
        assert len(paths) == 1, paths
        assert paths[0].name == "base_ASD_1_plan_min.png", paths[0].name
        assert paths[0].exists() and paths[0].stat().st_size > 0, paths[0]
    print("plot single-step stem/title OK")


def test_build_elevation_labels():
    """service.build_elevation_labels formats a model's elevation inventory
    (model length units) into combobox labels in the requested output unit."""
    elevations = [
        {"z": -18550.0, "label": "Base", "n_points": 42},
        {"z": 1900.0, "label": "+ 1.90", "n_points": 60},
        {"z": 2300.0, "label": "", "n_points": 5},
    ]
    # "model"/"" -> no conversion (labels stay in the model's own unit, mm).
    labels_model = service.build_elevation_labels(elevations, "mm", "model")
    assert labels_model[0] == "-18550  (Base, 42 pts)", labels_model
    assert labels_model[2] == "2300  (5 pts)", labels_model
    # Explicit "m" -> mm -> m conversion (÷1000).
    labels_m = service.build_elevation_labels(elevations, "mm", "m")
    assert labels_m[0] == "-18.55  (Base, 42 pts)", labels_m
    assert labels_m[1] == "1.9  (+ 1.90, 60 pts)", labels_m
    print("service.build_elevation_labels OK")


def test_units_module_factors():
    """etabs_extractor.units: resolve_target + factors sanity (model-aware
    unit conversion at the heart of the extraction/plotting pipeline)."""
    from etabs_extractor.units import UnitSystem, factors, resolve_target

    src = UnitSystem("N", "mm")
    # "model" on both dimensions -> no conversion.
    same = resolve_target(src, "model", "model")
    assert same == src
    ff, mf, lf = factors(src, same)
    assert ff == 1.0 and mf == 1.0 and lf == 1.0

    dst = resolve_target(src, "kN", "m")
    assert dst == UnitSystem("kN", "m")
    ff, mf, lf = factors(src, dst)
    assert abs(ff - 0.001) < 1e-12   # N -> kN
    assert abs(lf - 0.001) < 1e-12   # mm -> m
    assert abs(mf - 1e-6) < 1e-15    # N*mm -> kN*m
    print("units module factors OK")


def test_write_base_step_csv():
    """write_base_step_csv: split filename, case prefix, tag, and
    None-on-empty (no placeholder files)."""
    from etabs_extractor.io import write_base_step_csv
    from etabs_extractor.models import BASE_COLUMNS, JointReactionRecord

    recs = [
        JointReactionRecord(
            point="1", x=0.0, y=0.0, z=0.0,
            load_name="ASD Max", load_kind="COMBO",
            F1=1.0, F2=0.0, F3=10.0, M1=0.0, M2=0.0, M3=0.0,
            step_type="Min",
        ),
    ]
    with tempfile.TemporaryDirectory() as td:
        p = write_base_step_csv(recs, td, "ASD Max", load_kind="COMBO", step="Min")
        assert p is not None
        assert p.name == "base_combo_ASD_Max_min.csv", p.name
        df = pd.read_csv(p, encoding="utf-8")
        assert list(df.columns) == BASE_COLUMNS, list(df.columns)
        assert df.iloc[0]["step_type"] == "Min"
        # Case variant + tag suffix.
        p2 = write_base_step_csv(recs, td, "Dead", load_kind="CASE", step="Max", tag="K1")
        assert p2 is not None
        assert p2.name == "base_case_Dead_max_K1.csv", p2.name
        # Empty records -> None (no file written).
        assert write_base_step_csv([], td, "ASD Max", step="Min") is None
    print("write_base_step_csv OK")


def test_plot_base_reactions_steps():
    """steps=(absmax, max, min): one envelope load yields exactly 3 files
    (base_<load>_plan, _max, _min); a stepless load yields only the abs-max
    file.  Default steps=None keeps today's single-file behavior."""
    from etabs_extractor.plots import STEP_VARIANTS

    assert STEP_VARIANTS == ("absmax", "max", "min")
    df = _envelope_df()
    with tempfile.TemporaryDirectory() as td:
        paths = plot_base_reactions(
            df, td, steps=("absmax", "max", "min"),
            dpi=100, dynamic_size=False, figsize=(6, 5),
        )
        names = sorted(p.name for p in paths)
        assert names == [
            "base_DL_plan.png",
            "base_ENV_plan.png",
            "base_ENV_plan_max.png",
            "base_ENV_plan_min.png",
        ], names
        for p in paths:
            assert p.exists() and p.stat().st_size > 0, p

        # Default (steps=None) -> absmax only: today's behavior unchanged.
        with tempfile.TemporaryDirectory() as td2:
            paths2 = plot_base_reactions(
                df, td2, dpi=100, dynamic_size=False, figsize=(6, 5),
            )
            assert sorted(p.name for p in paths2) == [
                "base_DL_plan.png", "base_ENV_plan.png",
            ]
    print("plot_base_reactions steps variants OK")


def test_plot_steps_invalid_variant_raises():
    """An unknown step variant raises ValueError with the known list."""
    df = _envelope_df()
    try:
        build_base_reactions_figure(df, "ENV", step="bogus")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "absmax" in str(exc), str(exc)
    with tempfile.TemporaryDirectory() as td:
        try:
            plot_base_reactions(df, td, steps=["absmax", "nope"])
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "nope" in str(exc), str(exc)
    print("invalid step variant -> ValueError OK")


def test_build_figure_step_filter():
    """step='max'/'min' render only that envelope step's values (label-text
    assert); stepless data with step='max' yields None (no such rows)."""
    import matplotlib.pyplot as plt

    df = _envelope_df()
    df_env = df[df["load_name"] == "ENV"]

    fig_max = build_base_reactions_figure(df_env, "ENV", step="max")
    assert fig_max is not None
    texts = "\n".join(t.get_text() for t in fig_max.axes[0].texts)
    assert "Fz=100" in texts and "Fz=-30" in texts, texts
    assert "Fz=-60" not in texts and "Fz=-80" not in texts, texts
    assert "(Max)" in fig_max.axes[0].get_title(), fig_max.axes[0].get_title()
    plt.close(fig_max)

    fig_min = build_base_reactions_figure(df_env, "ENV", step="min")
    assert fig_min is not None
    texts_min = "\n".join(t.get_text() for t in fig_min.axes[0].texts)
    assert "Fz=-60" in texts_min and "Fz=-80" in texts_min, texts_min
    assert "(Min)" in fig_min.axes[0].get_title()
    plt.close(fig_min)

    # Abs max (default): per point, max-|value| across Max/Min rows.
    fig_abs = build_base_reactions_figure(df_env, "ENV")
    assert fig_abs is not None
    texts_abs = "\n".join(t.get_text() for t in fig_abs.axes[0].texts)
    assert "Fz=100" in texts_abs and "Fz=-80" in texts_abs, texts_abs
    assert "(Max)" not in fig_abs.axes[0].get_title()
    plt.close(fig_abs)

    # Stepless load: Max/Min variants have no rows -> no figure.
    df_dl = df[df["load_name"] == "DL"]
    assert build_base_reactions_figure(df_dl, "DL", step="max") is None
    print("build_base_reactions_figure step filter OK")


def test_save_batch_plots():
    """service.save_batch_plots: Batch plot dir wins; blank falls back to
    Output dir (extraction result) / Plot output or CSV parent (CSV result);
    no directory at all raises a clear error."""
    df = _envelope_df()
    result = {"df": df, "output_dir": None, "load_names": ["ENV", "DL"]}

    # 1. Explicit Batch plot dir.
    with tempfile.TemporaryDirectory() as td_batch:
        s = GuiSettings(batch_plot_dir=td_batch, dpi=100)
        paths = service.save_batch_plots(result, s)
        assert len(paths) == 4, [p.name for p in paths]
        assert all(p.parent == Path(td_batch) for p in paths), paths

    # 2. Blank Batch plot dir + extraction result -> Output dir.
    with tempfile.TemporaryDirectory() as td_out:
        s = GuiSettings(output_dir=td_out, dpi=100)
        extraction = {"df": df, "output_dir": td_out}
        paths = service.save_batch_plots(extraction, s)
        assert len(paths) == 4
        assert all(p.parent == Path(td_out) for p in paths)

    # 3. Blank Batch plot dir + CSV result -> Plot output dir, else CSV parent.
    with tempfile.TemporaryDirectory() as td_csv:
        csv_path = Path(td_csv) / "all_base_reactions.csv"
        csv_path.write_text("x,y,load_name\n", encoding="utf-8")
        s = GuiSettings(csv_path=str(csv_path), dpi=100)
        paths = service.save_batch_plots(result, s)
        assert all(p.parent == Path(td_csv) for p in paths)

        # Explicit Plot output dir wins over the CSV parent.
        with tempfile.TemporaryDirectory() as td_plot:
            s2 = GuiSettings(csv_path=str(csv_path),
                             plot_output_dir=td_plot, dpi=100)
            paths2 = service.save_batch_plots(result, s2)
            assert all(p.parent == Path(td_plot) for p in paths2)

    # 4. Nothing configured -> clear ValueError.
    try:
        service.save_batch_plots({"df": df, "output_dir": None}, GuiSettings(dpi=100))
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Batch plot" in str(exc) or "batch plot" in str(exc), str(exc)
    print("service.save_batch_plots fallback chain OK")


def test_save_batch_plots_steps_selection():
    """service.save_batch_plots honors settings.plot_steps: only the selected
    variants' files are written; empty selection raises a clear ValueError;
    default settings keep all three variants (regression guard)."""
    df = _envelope_df()
    result = {"df": df, "output_dir": None, "load_names": ["ENV", "DL"]}

    # 1. Default settings -> all three variants (absmax x2 loads + max + min).
    with tempfile.TemporaryDirectory() as td:
        paths = service.save_batch_plots(
            result, GuiSettings(batch_plot_dir=td, dpi=100))
        names = [p.name for p in paths]
        assert len(paths) == 4, names
        assert any("_plan_max.png" in n for n in names) and any(
            "_plan_min.png" in n for n in names), names

    # 2. Only absmax -> no _max/_min step-split files.
    with tempfile.TemporaryDirectory() as td:
        paths = service.save_batch_plots(
            result, GuiSettings(batch_plot_dir=td, dpi=100, plot_steps=["absmax"]))
        names = [p.name for p in paths]
        assert len(paths) == 2, names  # one absmax figure per load
        assert not any("_plan_max" in n or "_plan_min" in n for n in names), names

    # 3. Only Min -> only step-split Min files.
    with tempfile.TemporaryDirectory() as td:
        paths = service.save_batch_plots(
            result, GuiSettings(batch_plot_dir=td, dpi=100, plot_steps=["min"]))
        names = [p.name for p in paths]
        assert len(paths) == 1 and "_plan_min.png" in names[0], names

    # 4. Empty selection -> clear ValueError, before any file is written.
    with tempfile.TemporaryDirectory() as td:
        try:
            service.save_batch_plots(
                result, GuiSettings(batch_plot_dir=td, dpi=100, plot_steps=[]))
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "No plot steps selected" in str(exc), str(exc)
        assert not list(Path(td).iterdir()), "files written despite empty steps"
    print("service.save_batch_plots steps selection OK")


def run():
    test_gui_imports_without_display()
    test_build_figure_fixed_size()
    test_offsets_expand_axis_limits_not_canvas()
    test_build_figure_zero_offset_reproduces_base()
    test_plot_base_reactions_offset_threading()
    test_build_figure_label_offsets()
    test_build_figure_label_components()
    test_plot_base_reactions_label_kwargs()
    test_service_label_kwargs_and_csv_filter()
    test_build_figure_dynamic_size()
    test_build_figure_dynamic_offset_limits()
    test_build_figure_none_for_no_points()
    test_plot_base_reactions_dpi_figsize()
    test_plot_single_step_stem_and_title()
    test_plot_base_reactions_steps()
    test_plot_steps_invalid_variant_raises()
    test_build_figure_step_filter()
    test_save_batch_plots()
    test_save_batch_plots_steps_selection()
    test_write_base_step_csv()
    test_service_frame_mode_kwargs()
    test_service_extract_kwargs_mapping()
    test_load_selection_model()
    test_load_selection_model_kind_groups()
    test_inspect_active_model_fake()
    test_inspect_active_model_fake2()
    test_service_plot_kwargs_mapping()
    test_state_parsing()
    test_build_elevation_labels()
    test_units_module_factors()
    print("PASSED")


if __name__ == "__main__":
    run()
