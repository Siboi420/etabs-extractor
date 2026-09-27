"""Headed smoke test for the customtkinter GUI (``etabs_extractor.gui.app``).

Requires a real display (WSLg / X11 / native); prints "SKIPPED (no display)"
and exits 0 when none is available instead of failing.  No COM/ETABS
required — the model/session layers are never touched; this only exercises
the view: widget -> ``_collect_settings`` mapping, mode-scoped visibility
switching, and rendering a **synthetic** base-reaction result into the
embedded preview panel.
"""

from __future__ import annotations

import os
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")

if __package__ in (None, ""):
    # Test lives at <root>/etabs_extractor/tests/, so go up 3 levels to root.
    sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)


def _make_app():
    import tkinter as tk

    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError:
        return None

    from etabs_extractor.gui.app import EtabsExtractorApp

    app = EtabsExtractorApp()
    app.update_idletasks()
    app.withdraw()
    return app


def test_collect_settings_base_mode(app) -> None:
    app.model_field.set("D:\\fake\\fake_model.EDB")
    app.output_field.set("D:\\fake\\fake_out")
    app.tag_field.set("KM13")
    app.elevation_var.set("-16000")
    app.only_loaded_var.set(True)
    app.plot_after_var.set(True)
    app.load_field.set_items(["ASD 1", "ASD Max"], ["DL", "LL"])
    app.load_field._model.set_selected(["ASD 1", "DL"])
    app.force_unit_var.set("kN")
    app.length_unit_var.set("m")
    app.update_idletasks()

    s = app._collect_settings()
    assert s.model_path == "D:\\fake\\fake_model.EDB", s.model_path
    assert s.output_dir == "D:\\fake\\fake_out", s.output_dir
    assert s.tag == "KM13", s.tag
    assert s.extract_mode == "base", s.extract_mode
    assert s.elevation == "-16000", s.elevation
    assert s.only_loaded is True
    assert s.plot_after_extract is True
    assert s.selected_combos == ["ASD 1"], s.selected_combos
    assert s.selected_cases == ["DL"], s.selected_cases
    assert s.force_unit == "kN", s.force_unit
    assert s.length_unit == "m", s.length_unit
    print("collect_settings (base mode) OK")


def test_browse_buttons_mapped(app) -> None:
    """The sidebar's Model/Output Browse buttons must actually fit inside
    their field's real width (geometry, not on-screen ``ismapped`` — the app
    is withdrawn in this smoke test, which unmaps everything regardless of
    layout). The historical bug this guards against laid the button out past
    the frame's right edge, so it was never actually drawn/clickable.

    Scoped to the always-visible sidebar (fixed-width ``CTkScrollableFrame``):
    a ``CTkTabview`` tab's content only gets real stretch geometry once
    selected on a *mapped* window, which a withdrawn smoke-test window never
    is — so the same check on e.g. the CSV tab's fields is not meaningful
    here (the class itself, ``DirectoryField``/``FileField``, is shared and
    already exercised by these two)."""
    app.update_idletasks()
    for name, field in (
        ("model_field", app.model_field),
        ("output_field", app.output_field),
    ):
        assert field.btn.winfo_manager() == "grid", f"{name}.btn has no geometry manager"
        right_edge = field.btn.winfo_x() + field.btn.winfo_width()
        assert 0 < right_edge <= field.winfo_width(), (
            f"{name}.btn right edge {right_edge} exceeds field width {field.winfo_width()}"
        )
    print("Browse buttons mapped OK")


def test_units_and_elevation_roundtrip(app) -> None:
    """Model units + elevation inventory feed the units hint and the
    elevation combobox, in the currently selected output length unit."""
    app._model_units = {"force": "kN", "length": "m"}
    app._elevations = [
        {"z": -18.55, "label": "Base", "n_points": 42},
        {"z": 1.9, "label": "+ 1.90", "n_points": 60},
    ]
    app.length_unit_var.set("model")
    app._on_units_changed()
    app.update_idletasks()
    assert "kN, m" in app.units_hint_var.get(), app.units_hint_var.get()
    values = list(app.elevation_combo.cget("values") or [])
    assert values[0] == "-18.55  (Base, 42 pts)", values

    app.length_unit_var.set("mm")
    app._on_units_changed()
    values_mm = list(app.elevation_combo.cget("values") or [])
    assert values_mm[0] == "-18550  (Base, 42 pts)", values_mm

    app.elevation_var.set(values_mm[0])
    s = app._collect_settings()
    from etabs_extractor.gui.state import parse_elevation
    assert parse_elevation(s.elevation) == -18550.0, s.elevation

    app.length_unit_var.set("model")
    app._on_units_changed()
    print("units + elevation roundtrip OK")


def test_mode_switch_visibility(app) -> None:
    app.section_field.set_items(["B1", "B2"], [])
    app.section_field._model.set_selected(["B1"])

    app._on_mode_changed("Frame forces")
    app.update_idletasks()
    assert app.base_filter.winfo_manager() == "", "base_filter should be unpacked in frame mode"
    assert app.frame_filter.winfo_manager() == "pack", "frame_filter should be packed in frame mode"
    assert app.base_preview.grid_info() == {}, "base_preview should be grid_forgotten in frame mode"
    assert app.frame_preview.grid_info() != {}, "frame_preview should be gridded in frame mode"

    s = app._collect_settings()
    assert s.extract_mode == "frame", s.extract_mode
    assert s.selected_sections == ["B1"], s.selected_sections

    app._on_mode_changed("Base reactions")
    app.update_idletasks()
    assert app.frame_filter.winfo_manager() == "", "frame_filter should be unpacked in base mode"
    assert app.base_filter.winfo_manager() == "pack", "base_filter should be packed in base mode"
    assert app.frame_preview.grid_info() == {}, "frame_preview should be grid_forgotten in base mode"
    assert app.base_preview.grid_info() != {}, "base_preview should be gridded in base mode"
    print("mode switch visibility OK")


def _synthetic_base_result() -> dict:
    from etabs_extractor.models import JointReactionRecord, to_base_dataframe

    records = [
        JointReactionRecord(
            point="1", x=0.0, y=0.0, z=-16000.0,
            load_name="ASD 1", load_kind="COMBO", step_type="",
            F1=1.0, F2=2.0, F3=100.0, M1=0.0, M2=5.0, M3=6.0,
        ),
        JointReactionRecord(
            point="2", x=5000.0, y=0.0, z=-16000.0,
            load_name="ASD 1", load_kind="COMBO", step_type="",
            F1=1.5, F2=2.5, F3=120.0, M1=0.0, M2=5.5, M3=6.5,
        ),
    ]
    df = to_base_dataframe(records)
    per_load: dict = {}
    for name, grp in df.groupby("load_name", sort=True):
        per_load[name] = grp
    return {
        "df": df,
        "per_load": per_load,
        "records": records,
        "output_dir": None,
        "tag": None,
        "load_names": list(per_load.keys()),
        "plot_paths": [],
    }


def _synthetic_envelope_result() -> dict:
    """Synthetic base-reaction result with Max/Min envelope steps, for
    exercising the step dropdown (re-render on change + Max/Min filtering)."""
    from etabs_extractor.models import JointReactionRecord, to_base_dataframe

    records = []
    for step, f3 in (("Max", 100.0), ("Min", -60.0)):
        records.append(
            JointReactionRecord(
                point="1", x=0.0, y=0.0, z=-16000.0,
                load_name="ENV", load_kind="COMBO", step_type=step,
                F1=1.0, F2=2.0, F3=f3, M1=0.0, M2=5.0, M3=6.0,
            ),
        )
    df = to_base_dataframe(records)
    per_load: dict = {}
    for name, grp in df.groupby("load_name", sort=True):
        per_load[name] = grp
    return {
        "df": df,
        "per_load": per_load,
        "records": records,
        "output_dir": None,
        "tag": None,
        "load_names": list(per_load.keys()),
        "plot_paths": [],
    }


def test_base_preview_renders_synthetic_result(app) -> None:
    result = _synthetic_base_result()
    app._result = result
    app.base_preview.set_result(result)
    app.update_idletasks()
    fig = app.base_preview.preview.current_figure()
    assert fig is not None, "expected a rendered figure for the synthetic result"
    print("base preview render (synthetic data) OK")


def test_base_preview_step_dropdown(app) -> None:
    """Step dropdown exists with the three variants; switching re-renders, and
    a stepless load falls back to abs max with a log note."""
    from etabs_extractor.gui.state import STEP_CHOICES

    assert list(app.base_preview.step_menu.cget("values")) == list(STEP_CHOICES)
    assert app.base_preview._batch_saver == app._on_batch_save, (
        "Batch save plots button must be wired to the app's batch saver"
    )

    # Envelope data: switching to Max re-renders a figure.
    result = _synthetic_envelope_result()
    app._result = result
    app.base_preview.set_result(result)
    app.update_idletasks()
    assert app.base_preview.preview.current_figure() is not None

    app.base_preview.step_var.set("Max")
    app.base_preview._render_current()
    app.update_idletasks()
    fig = app.base_preview.preview.current_figure()
    assert fig is not None, "Max step re-render failed"
    texts = "\\n".join(t.get_text() for t in fig.axes[0].texts)
    assert "Fz=100" in texts and "Fz=-60" not in texts, texts

    # Stepless data: Max selection falls back to abs max (still renders).
    app._result = _synthetic_base_result()
    app.base_preview.set_result(app._result)
    app.update_idletasks()
    app.base_preview.step_var.set("Max")
    app.base_preview._render_current()
    app.update_idletasks()
    assert app.base_preview.preview.current_figure() is not None, (
        "stepless load should fall back to abs max"
    )
    app.base_preview.step_var.set("Abs max")
    print("base preview step dropdown OK")


def test_batch_plot_dir_roundtrip(app) -> None:
    """Batch plot dir field round-trips through _collect_settings (both modes)."""
    batch_dir = tempfile.mkdtemp(prefix="batch_plots_")
    app.batch_plot_field.set(batch_dir)
    app.update_idletasks()
    s = app._collect_settings()
    assert s.batch_plot_dir == batch_dir, s.batch_plot_dir

    app._on_mode_changed("Frame forces")
    app.update_idletasks()
    s_frame = app._collect_settings()
    assert s_frame.batch_plot_dir == batch_dir, s_frame.batch_plot_dir
    app._on_mode_changed("Base reactions")
    app.update_idletasks()
    app.batch_plot_field.set("")
    print("batch plot dir roundtrip OK")


def main() -> None:
    app = _make_app()
    if app is None:
        print("SKIPPED (no display)")
        return
    try:
        test_collect_settings_base_mode(app)
        test_browse_buttons_mapped(app)
        test_units_and_elevation_roundtrip(app)
        test_mode_switch_visibility(app)
        test_base_preview_renders_synthetic_result(app)
        test_base_preview_step_dropdown(app)
        test_batch_plot_dir_roundtrip(app)
    finally:
        app.destroy()
    print("PASSED")


if __name__ == "__main__":
    main()
