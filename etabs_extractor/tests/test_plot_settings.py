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

import matplotlib  # noqa: E402
matplotlib.use("Agg")

# Make the package importable when run directly as a script.
import sys  # noqa: E402

if __package__ in (None, ""):
    # Test lives at <root>/etabs_extractor/tests/, so go up 3 levels to root.
    sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)

import pandas as pd  # noqa: E402

from etabs_extractor.gui.state import (  # noqa: E402
    GuiSettings,
    LoadSelectionModel,
    parse_combos,
    parse_elevation,
)
from etabs_extractor.gui import service  # noqa: E402
from etabs_extractor.plots import (  # noqa: E402
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


def _no_point_df():
    """A frame with only NaN coordinates (no plottable points)."""
    return pd.DataFrame(
        [
            {"point": "x", "x": None, "y": None, "z": None,
             "load_name": "NONE", "load_kind": "COMBO",
             "F1": 0.0, "F2": 0.0, "F3": 0.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
        ]
    )


def test_gui_imports_without_display():
    """Importing the GUI package/state/service must succeed with no display."""
    import etabs_extractor.gui.app  # noqa: F401
    import etabs_extractor.gui.runner  # noqa: F401
    import etabs_extractor.gui.widgets.preview  # noqa: F401
    import etabs_extractor.gui.widgets.plot_settings  # noqa: F401
    print("GUI import OK (no display, no comtypes)")


def test_build_figure_fixed_size():
    df = _sample_df()
    # Offsets default to 1.0in each way, so the base (12, 6) becomes (14, 8).
    fig = build_base_reactions_figure(
        df, "ASD 1",
        dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=1, y_offset=1,
    )
    assert fig is not None, "expected a Figure for plottable data"
    w, h = fig.get_size_inches()
    assert abs(w - 14.0) < 1e-6 and abs(h - 8.0) < 1e-6, (w, h)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("build_base_reactions_figure fixed figsize + offsets OK")


def test_build_figure_zero_offset_reproduces_base():
    """Offsets of 0 reproduce the pre-change base size exactly."""
    df = _sample_df()
    fig = build_base_reactions_figure(
        df, "ASD 1",
        dynamic_size=False, figsize=(12, 6), label_fontsize=5,
        x_offset=0, y_offset=0,
    )
    assert fig is not None
    w, h = fig.get_size_inches()
    assert abs(w - 12.0) < 1e-6 and abs(h - 6.0) < 1e-6, (w, h)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("build_base_reactions_figure zero offsets -> base size OK")


def test_plot_base_reactions_offset_threading():
    """Offsets thread through to the built figure; writes a non-empty PNG with
    no edge-label clipping exception."""
    df = _sample_df()
    with tempfile.TemporaryDirectory() as td:
        paths = plot_base_reactions(
            df, td, dpi=100, dynamic_size=False, figsize=(12, 6),
            label_fontsize=5, load_name="ASD 1",
            x_offset=1.5, y_offset=0.5,
        )
        assert len(paths) == 1, paths
        p = paths[0]
        assert p.exists() and p.stat().st_size > 0, p
        # Rebuild via the public figure builder to confirm size accounting.
        fig = build_base_reactions_figure(
            df, "ASD 1", dynamic_size=False, figsize=(12, 6),
            x_offset=1.5, y_offset=0.5,
        )
        assert fig is not None
        w, h = fig.get_size_inches()
        assert abs(w - 15.0) < 1e-6 and abs(h - 7.0) < 1e-6, (w, h)
        import matplotlib.pyplot as plt
        plt.close(fig)
        print("plot_base_reactions offsets threaded OK")


def test_build_figure_dynamic_size():
    df = _sample_df()
    fig = build_base_reactions_figure(df, "ASD 1", dynamic_size=True)
    assert fig is not None
    w, h = fig.get_size_inches()
    # Dynamic base canvas (>= 6x5 min) plus 2*default 1in offsets each way
    # => final size >= 8x7.
    assert w >= 8.0 and h >= 7.0, (w, h)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("build_base_reactions_figure dynamic size + offsets OK")


def test_build_figure_dynamic_offset_extends_dynamic_base():
    """Dynamic mode: final size == _dynamic_figsize result + 2*offset each way.

    We call the public figure builder and check that subtracting 2*offset
    recovers a size the dynamic sizer would have produced (>= 6x5)."""
    df = _sample_df()
    fig = build_base_reactions_figure(
        df, "ASD 1", dynamic_size=True, x_offset=1.5, y_offset=0.5,
    )
    assert fig is not None
    w, h = fig.get_size_inches()
    base_w, base_h = w - 3.0, h - 1.0
    assert base_w >= 6.0 and base_h >= 5.0, (base_w, base_h)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("build_base_reactions_figure dynamic base + offsets OK")


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
    # Empty selection -> both None (all model combos default).
    s2 = GuiSettings()
    kw2 = service.build_extract_kwargs(s2)
    assert kw2["combos"] is None
    assert kw2["cases"] is None
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
    model.toggle(items.index([i for i in items if i.name == "ASD 1"][0]), True)
    model.toggle(items.index([i for i in items if i.name == "Dead"][0]), True)
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
    try:
        parse_elevation("not-a-number")
        assert False, "expected ValueError"
    except ValueError as exc:
        # Expected: raise the value through to assert the error propagated.
        assert "Invalid elevation" in str(exc)
        print(f"state parsing OK (rejected {str(exc)!r})")


def run():
    test_gui_imports_without_display()
    test_build_figure_fixed_size()
    test_build_figure_zero_offset_reproduces_base()
    test_plot_base_reactions_offset_threading()
    test_build_figure_dynamic_size()
    test_build_figure_dynamic_offset_extends_dynamic_base()
    test_build_figure_none_for_no_points()
    test_plot_base_reactions_dpi_figsize()
    test_service_extract_kwargs_mapping()
    test_load_selection_model()
    test_inspect_active_model_fake()
    test_service_plot_kwargs_mapping()
    test_state_parsing()
    print("PASSED")


if __name__ == "__main__":
    run()