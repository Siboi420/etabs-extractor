"""Dry-run test for etabs_extractor — exercises the real extraction →
DataFrame → CSV pipeline against a synthetic (fake) SAP model, with no COM
dependency.

All force values in the fake are fabricated/synthetic; this test asserts on
pipeline mechanics (column order, row counts, CSV outputs), NOT on any real
ETABS results.  It runs on any platform (WSL included) because it never
touches comtypes.
"""

from __future__ import annotations

import tempfile
import os
from pathlib import Path

# Use the non-interactive Agg backend for headless plotting in tests, and
# set it before importing anything that might touch pyplot.  This keeps the
# dry-run fully offline (no display, no COM).
import matplotlib  # noqa: E402
matplotlib.use("Agg")

# Make the package importable when run directly as a script.
import sys  # noqa: E402

if __package__ in (None, ""):
    # Running directly as a script: make the package importable.
    # Test lives at <root>/etabs_extractor/tests/, so go up 3 levels to root.
    sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)

import pandas as pd  # noqa: E402

import etabs_extractor as etabs_extractor
from etabs_extractor import connection as _extractor_connection
from etabs_extractor.results import extract_forces


# ---------------------------------------------------------------------------
# Fake SAP-model objects providing the duck-typed surface EtabsSession exposes.
# ---------------------------------------------------------------------------
class _FakeFrameForce:
    """Mirrors ``Results.FrameForce(name, itemTypeElm, ...)``."""

    def __init__(self, data_by_frame: dict, combos: list[str]) -> None:
        self.data_by_frame = data_by_frame
        self.combos = combos
        self._setup: "_FakeSetup | None" = None  # reference set by _FakeResults

    def _records_for(self, frame: str) -> list[dict]:
        """Return the records for ``frame`` filtered to the currently-selected
        output load names — emulating COM selection behaviour."""
        selected = None
        if self._setup is not None:
            # Respect whichever stream was selected most recently.
            if self._setup.selected_combos:
                selected = set(self._setup.selected_combos)
            elif self._setup.selected_cases:
                selected = set(self._setup.selected_cases)
        recs = self.data_by_frame.get(frame, [])
        if selected is None:
            return recs
        return [r for r in recs if r["load"] in selected]

    def __call__(self, Name, ItemTypeElm, NumberResults, Obj, ObjSta, Elm,
                 ElmSta, LoadCase, StepType, StepNum, P, V2, V3, T, M2, M3):
        recs = self.data_by_frame.get(Name, [])
        NumberResults = len(recs)
        obj = []; obj_sta = []; elm = []; elm_sta = []
        lc = []; st = []; sn = []
        p = []; v2 = []; v3 = []; t = []; m2 = []; m3 = []
        for r in recs:
            obj.append(Name)
            obj_sta.append(r["station"])
            elm.append(Name + "-1")
            elm_sta.append(r["station"])
            lc.append(r["load"])
            st.append("")
            sn.append(0)
            p.append(r["P"]); v2.append(r["V2"]); v3.append(r["V3"])
            t.append(r["T"]); m2.append(r["M2"]); m3.append(r["M3"])
        # COM-ish pass-by-reference: assign into the passed lists.
        Obj[:] = obj; ObjSta[:] = obj_sta; Elm[:] = elm; ElmSta[:] = elm_sta
        LoadCase[:] = lc; StepType[:] = st; StepNum[:] = sn
        P[:] = p; V2[:] = v2; V3[:] = v3; T[:] = t; M2[:] = m2; M3[:] = m3
        return 0


class _FakeSetup:
    def __init__(self) -> None:
        self.selected_combos = []
        self.selected_cases = []

    def DeselectAllCasesAndCombosForOutput(self) -> None:
        self.selected_combos = []
        self.selected_cases = []

    def SetComboSelectedForOutput(self, name, sel) -> None:
        if sel:
            self.selected_combos.append(name)

    def SetCaseSelectedForOutput(self, name, sel) -> None:
        if sel:
            self.selected_cases.append(name)


class _FakeFrameObj:
    def __init__(self, names: list[str], sections: dict) -> None:
        self.names = names
        self.sections = sections

    def GetNameList(self, NumberNames, MyName):
        NumberNames = len(self.names)
        MyName[:] = self.names
        return 0

    def GetSection(self, Name):
        return (0, self.sections.get(Name, ""))


class _FakeRespCombo:
    def __init__(self, names: list[str]) -> None:
        self.names = names

    def GetNameList(self, NumberNames, MyName):
        NumberNames = len(self.names)
        MyName[:] = self.names
        return 0


class _FakeLoadCases:
    def __init__(self, names: list[str]) -> None:
        self.names = names

    def GetNameList(self, NumberNames, MyName):
        NumberNames = len(self.names)
        MyName[:] = self.names
        return 0


class _FakeResults:
    def __init__(self, data_by_frame: dict, combos: list[str]) -> None:
        self.Setup = _FakeSetup()
        self.FrameForce = _FakeFrameForce(data_by_frame, combos)
        self.FrameForce._setup = self.Setup
        self.JointReact = _FakeJointReact(_REACT_BY_POINT, combos)
        self.JointReact._setup = self.Setup


class _FakeJointReact:
    """Mirrors ``Results.JointReact(name, itemTypeElm, ...)`` with synthetic
    per-point reactions.  All values are fabricated (pipeline test only)."""

    def __init__(self, data_by_point: dict, combos: list[str]) -> None:
        self.data_by_point = data_by_point
        self.combos = combos
        self._setup: "_FakeSetup | None" = None

    def _records_for(self, point: str) -> list[dict]:
        selected = None
        if self._setup is not None:
            if self._setup.selected_combos:
                selected = set(self._setup.selected_combos)
            elif self._setup.selected_cases:
                selected = set(self._setup.selected_cases)
        recs = self.data_by_point.get(point, [])
        if selected is None:
            return recs
        return [r for r in recs if r["load"] in selected]

    def __call__(self, Name, ItemTypeElm, NumberResults, Obj, Elm, LoadCase,
                 StepType, StepNum, F1, F2, F3, M1, M2, M3):
        recs = self.data_by_point.get(Name, [])
        NumberResults = len(recs)
        obj = []; elm = []; lc = []; st = []; sn = []
        f1 = []; f2 = []; f3 = []; m1 = []; m2 = []; m3 = []
        for r in recs:
            obj.append(Name)
            elm.append(Name)
            lc.append(r["load"])
            st.append("")
            sn.append(0)
            f1.append(r["F1"]); f2.append(r["F2"]); f3.append(r["F3"])
            m1.append(r["M1"]); m2.append(r["M2"]); m3.append(r["M3"])
        Obj[:] = obj; Elm[:] = elm; LoadCase[:] = lc
        StepType[:] = st; StepNum[:] = sn
        F1[:] = f1; F2[:] = f2; F3[:] = f3
        M1[:] = m1; M2[:] = m2; M3[:] = m3
        return 0


class _FakePointObj:
    def __init__(self, names: list[str], coords: dict) -> None:
        self.names = names
        self.coords = coords

    def GetNameList(self, NumberNames, MyName):
        NumberNames = len(self.names)
        MyName[:] = self.names
        return 0

    def GetCoordCartesian(self, Name):
        c = self.coords.get(Name, (0.0, 0.0, 0.0))
        return (c[0], c[1], c[2], 0)


class _FakeFile:
    def __init__(self, model_filename: str = "D:\\Models\\synthetic_model.EDB") -> None:
        self.model_filename = model_filename

    def OpenFile(self, path):
        return 0


class _FakeAnalyze:
    def RunAnalysis(self):
        return 0


class _FakeSapModel:
    """Full fake exposing the EtabsSession surface used by extract_forces."""

    def __init__(self, *, frames, sections, combos, cases, data_by_frame,
                 point_names, point_coords,
                 model_filename: str = "D:\\Models\\synthetic_model.EDB"):
        self.File = _FakeFile(model_filename=model_filename)
        self.Analyze = _FakeAnalyze()
        self.FrameObj = _FakeFrameObj(frames, sections)
        self.RespCombo = _FakeRespCombo(combos)
        self.LoadCases = _FakeLoadCases(cases)
        self.PointObj = _FakePointObj(point_names, point_coords)
        self.Results = _FakeResults(data_by_frame, combos)
        self.model_filename = model_filename

    def GetModelFilename(self, include_path=True):
        """Mirror the real ``cSapModel.GetModelFilename`` method (on the model
        object, not the File interface).

        ``GetModelFilename(bool include_path) -> string`` is a cSapModel method
        in the CSI OAPI.  The comtypes return shape is a plain ``str`` (or a
        ``[value, retcode]`` sequence), so the fake returns a plain string for
        the full path and a bare name when ``include_path`` is False."""
        if not include_path:
            return self.model_filename.split("\\")[-1]
        return self.model_filename


class _FakeSession(_extractor_connection.EtabsSession):
    """Complete surface the orchestrators call; subclasses EtabsSession so
    the ``session`` parameter type-check passes while behaving as a fake."""

    def __init__(self, sap_model: _FakeSapModel) -> None:
        super().__init__(helper=sap_model, sap_model=sap_model)

    def get_frame_names(self):
        return self.sap_model.FrameObj.names

    def get_combo_names(self):
        return self.sap_model.RespCombo.names

    def get_case_names(self):
        return self.sap_model.LoadCases.names

    def get_section_for_frame(self, frame):
        return self.sap_model.FrameObj.sections.get(frame, "")

    def get_point_names(self):
        return self.sap_model.PointObj.names

    def get_point_coords(self, point):
        c = self.sap_model.PointObj.coords.get(point, (None, None, None))
        return (c[0], c[1], c[2])

    def setup_select_combos(self, combos):
        s = self.sap_model.Results.Setup
        s.DeselectAllCasesAndCombosForOutput()
        for c in (combos or []):
            s.SetComboSelectedForOutput(c, True)

    def setup_select_cases(self, cases):
        s = self.sap_model.Results.Setup
        s.DeselectAllCasesAndCombosForOutput()
        for c in (cases or []):
            s.SetCaseSelectedForOutput(c, True)

    def run_analysis(self):
        return self.sap_model.Analyze.RunAnalysis()

    def frame_force(self, frame, item_type_elm=0):
        """Return the post-COM tuple shaped exactly like the real
        ``EtabsSession.frame_force`` — derived directly from synthetic data
        (no COM by-ref emulation needed)."""
        data = self._ff_data(frame, item_type_elm)
        if not data:
            return None
        NumberResults = len(data)
        Obj          = [frame for _ in data]
        ObjSta       = [r["station"] for r in data]
        Elm          = [frame + "-1" for _ in data]
        ElmSta       = [r["station"] for r in data]
        LoadCase     = [r["load"] for r in data]
        StepType     = [r.get("step", "") for r in data]
        StepNum      = [r.get("stepnum", 0) for r in data]
        P  = [r["P"]  for r in data]
        V2 = [r["V2"] for r in data]
        V3 = [r["V3"] for r in data]
        T  = [r["T"]  for r in data]
        M2 = [r["M2"] for r in data]
        M3 = [r["M3"] for r in data]
        return (NumberResults, Obj, ObjSta, Elm, ElmSta, LoadCase, StepType,
                StepNum, P, V2, V3, T, M2, M3)

    def _ff_data(self, frame, item_type_elm):
        return self.sap_model.Results.FrameForce._records_for(frame)

    def joint_react(self, point, item_type_elm=0):
        """Return the post-COM tuple shaped exactly like the real
        ``EtabsSession.joint_react`` — derived directly from synthetic data."""
        data = self.sap_model.Results.JointReact._records_for(point)
        if not data:
            return None
        NumberResults = len(data)
        Obj          = [point for _ in data]
        Elm          = [point for _ in data]
        LoadCase     = [r["load"] for r in data]
        StepType     = [r.get("step", "") for r in data]
        StepNum      = [r.get("stepnum", 0) for r in data]
        F1 = [r["F1"] for r in data]
        F2 = [r["F2"] for r in data]
        F3 = [r["F3"] for r in data]
        M1 = [r["M1"] for r in data]
        M2 = [r["M2"] for r in data]
        M3 = [r["M3"] for r in data]
        return (NumberResults, Obj, Elm, LoadCase, StepType, StepNum,
                F1, F2, F3, M1, M2, M3)


def _make_session(frames, sections, combos, cases, data_by_frame,
                  point_names=None, point_coords=None):
    sap = _FakeSapModel(
        frames=frames, sections=sections,
        combos=combos, cases=cases, data_by_frame=data_by_frame,
        point_names=point_names or ["1", "2", "3"],
        point_coords=point_coords or {
            "1": (0.0, 0.0, 0.0),
            "2": (6000.0, 0.0, 0.0),
            "3": (6000.0, 3000.0, 0.0),
        },
    )
    return _FakeSession(sap)


# ---------------------------------------------------------------------------
# Build synthetic data and run the real pipeline.
# ---------------------------------------------------------------------------
def _build_frame_synthetic():
    frames = ["B1", "B2", "C1"]
    sections = {"B1": "B1", "B2": "B2", "C1": "COL1"}
    combos = ["ASD 1", "LRFD 1"]
    cases = ["Dead", "Live"]
    data_by_frame = {
        "B1": [
            {"station": 0.0, "load": "ASD 1", "P": -10.0, "V2": 1.0, "V3": 2.0, "T": 0.1, "M2": 5.0, "M3": 20.0},
            {"station": 1000.0, "load": "ASD 1", "P": -9.0, "V2": 0.5, "V3": 1.5, "T": 0.2, "M2": 4.0, "M3": 15.0},
            {"station": 0.0, "load": "LRFD 1", "P": -15.0, "V2": 1.5, "V3": 3.0, "T": 0.3, "M2": 6.0, "M3": 30.0},
            {"station": 0.0, "load": "Dead", "P": -6.0, "V2": 0.6, "V3": 1.0, "T": 0.05, "M2": 2.5, "M3": 10.0},
            {"station": 0.0, "load": "Live", "P": -4.0, "V2": 0.3, "V3": 0.7, "T": 0.02, "M2": 1.5, "M3": 6.0},
        ],
        "B2": [
            {"station": 0.0, "load": "ASD 1", "P": -5.0, "V2": 0.2, "V3": 0.8, "T": 0.0, "M2": 2.0, "M3": 8.0},
            {"station": 1200.0, "load": "LRFD 1", "P": -8.0, "V2": 0.4, "V3": 1.0, "T": 0.1, "M2": 3.0, "M3": 12.0},
            {"station": 0.0, "load": "Dead", "P": -3.0, "V2": 0.1, "V3": 0.4, "T": 0.0, "M2": 1.0, "M3": 4.0},
        ],
        "C1": [
            {"station": 0.0, "load": "ASD 1", "P": -100.0, "V2": 5.0, "V3": 6.0, "T": 1.0, "M2": 10.0, "M3": 50.0},
            {"station": 0.0, "load": "Live", "P": -50.0, "V2": 2.0, "V3": 3.0, "T": 0.5, "M2": 5.0, "M3": 25.0},
        ],
    }
    return frames, sections, combos, cases, data_by_frame


# Synthetic per-point reactions (fabricated; pipeline test only).  ``1/2`` are
# combos-sourced, ``3`` also has a Dead case to exercise the CASE stream.
_REACT_BY_POINT = {
    "1": [
        {"load": "ASD 1", "F1": 10.0, "F2": 2.0, "F3": 120.0, "M1": 1.0, "M2": 3.0, "M3": 0.5},
        {"load": "LRFD 1", "F1": 15.0, "F2": 3.0, "F3": 180.0, "M1": 1.5, "M2": 4.0, "M3": 0.8},
        {"load": "Dead", "F1": 5.0, "F2": 1.0, "F3": 60.0, "M1": 0.5, "M2": 1.5, "M3": 0.2},
    ],
    "2": [
        {"load": "ASD 1", "F1": -8.0, "F2": -1.0, "F3": 110.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
        {"load": "LRFD 1", "F1": -12.0, "F2": -1.5, "F3": 165.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
    ],
    "3": [
        {"load": "ASD 1", "F1": 3.0, "F2": 4.0, "F3": 80.0, "M1": 2.0, "M2": 1.0, "M3": 0.0},
        {"load": "Dead", "F1": 1.5, "F2": 2.0, "F3": 40.0, "M1": 1.0, "M2": 0.5, "M3": 0.0},
    ],
    # Point 4: an unrestrained/released support carrying no load at all.
    "4": [
        {"load": "ASD 1", "F1": 0.0, "F2": 0.0, "F3": 0.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
        {"load": "LRFD 1", "F1": 0.0, "F2": 0.0, "F3": 0.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
    ],
}

# Global coordinates for the synthetic points (x, y, z); z is the elevation.
_REACT_COORDS = {
    "1": (0.0, 0.0, 0.0),
    "2": (6000.0, 0.0, 0.0),
    "3": (6000.0, 3000.0, 3000.0),
    "4": (3000.0, 3000.0, -5000.0),
}


def _build_synthetic():
    """Return all synthetic data including point names/coords for the base
    reaction path."""
    frames, sections, combos, cases, data_by_frame = _build_frame_synthetic()
    return frames, sections, combos, cases, data_by_frame


def run():
    frames, sections, combos, cases, data_by_frame = _build_synthetic()
    session = _make_session(
        frames, sections, combos, cases, data_by_frame,
        point_names=list(_REACT_BY_POINT),
        point_coords=_REACT_COORDS,
    )

    from etabs_extractor.results import extract_forces

    with tempfile.TemporaryDirectory(prefix="e2k_dryrun_") as td:
        out = Path(td)
        # Use a temp model path (non-existent is fine for the fake session —
        # it never calls File.OpenFile because we pass the session directly).
        df, per_load, records = extract_forces(
            "synthetic_model.$et", str(out),
            session=session,
            all_requested=False,  # combos only (default scope)
        )

        assert isinstance(df, pd.DataFrame), "expected consolidated DataFrame"
        assert list(df.columns) == [
            "frame", "section", "station", "load_name", "load_kind",
            "P", "V2", "V3", "T", "M2", "M3", "obj_sta", "elm", "elm_sta",
        ], f"column order mismatch: {list(df.columns)}"

        # Combos-only by default: every row must be load_kind COMBO.
        assert set(df["load_kind"].unique()) == {"COMBO"}, df["load_kind"].unique()

        total_records = sum(len(v) for v in data_by_frame.values())
        expected_combo_rows = sum(
            1 for recs in data_by_frame.values() for r in recs if r["load"] in combos
        )
        assert len(records) == expected_combo_rows, (len(records), expected_combo_rows)
        assert len(df) == expected_combo_rows, (len(df), expected_combo_rows)

        # per_load must contain each combo.
        assert set(per_load.keys()) == set(combos), set(per_load.keys())
        # No load cases requested (default).
        assert "Dead" not in per_load and "Live" not in per_load

        # CSV verification.
        all_csv = out / "all_forces.csv"
        assert all_csv.exists(), "all_forces.csv not written"
        csv_df = pd.read_csv(all_csv, encoding="utf-8")
        assert list(csv_df.columns) == list(df.columns), "CSV column mismatch"
        assert len(csv_df) == expected_combo_rows, (len(csv_df), expected_combo_rows)

        # Per-combo CSV files.
        combo_dir = out
        combo_files = [f for f in os.listdir(combo_dir) if f.startswith("combo_")]
        assert len(combo_files) == len(combos), combo_files
        for c in combos:
            safe = c.replace(" ", "_")
            assert (combo_dir / f"combo_{safe}.csv").exists(), safe

        # Envelope summary exists and has expected shape.
        env_csv = out / "envelope_summary.csv"
        assert env_csv.exists(), "envelope_summary.csv not written"
        env = pd.read_csv(env_csv, encoding="utf-8")
        assert set(env.columns) >= {"frame", "load_name", "P_min", "P_max"}

        # Case-selection path sanity: extract cases instead.
        dfc, perc, _recs = extract_forces(
            "synthetic_model.$et", str(out),
            session=session,
            cases=["Dead", "Live"],
        )
        assert set(dfc["load_kind"].unique()) == {"CASE"}
        assert set(perc.keys()) == {"Dead", "Live"}

        # ---- Base (joint) reaction path --------------------------------------
        from etabs_extractor.models import BASE_COLUMNS
        from etabs_extractor.results import extract_base_reactions

        bdf, bper_load, brecs = extract_base_reactions(
            "synthetic_model.$et", str(out),
            session=session,
            all_requested=False,  # combos only (default scope)
        )

        assert isinstance(bdf, pd.DataFrame), "expected base consolidated DataFrame"
        assert list(bdf.columns) == BASE_COLUMNS, f"base column mismatch: {list(bdf.columns)}"

        # Combos-only by default: every row must be load_kind COMBO.
        assert set(bdf["load_kind"].unique()) == {"COMBO"}, bdf["load_kind"].unique()

        # x/y/z present and populated (coordinates attached).
        for c in ("x", "y", "z"):
            assert c in bdf.columns, c
            assert bool(bdf[c].notna().all()), f"{c} should be populated"
        # One point ("3") is at z=3000 elevation; ensure it's captured.
        assert 3000.0 in set(bdf["z"]), set(bdf["z"])

        expected_reaction_rows = sum(
            1 for recs in _REACT_BY_POINT.values() for r in recs if r["load"] in combos
        )
        assert len(brecs) == expected_reaction_rows, (len(brecs), expected_reaction_rows)
        assert len(bdf) == expected_reaction_rows, (len(bdf), expected_reaction_rows)
        assert set(bper_load.keys()) == set(combos), set(bper_load.keys())

        # CSV verification.
        all_base_csv = out / "all_base_reactions.csv"
        assert all_base_csv.exists(), "all_base_reactions.csv not written"
        bcsv = pd.read_csv(all_base_csv, encoding="utf-8")
        assert list(bcsv.columns) == BASE_COLUMNS, "base CSV column mismatch"
        assert len(bcsv) == expected_reaction_rows, (len(bcsv), expected_reaction_rows)

        # Per-load base CSV files.
        base_combo_files = [
            f for f in os.listdir(out) if f.startswith("base_combo_")
        ]
        assert len(base_combo_files) == len(combos), base_combo_files
        for c in combos:
            safe = c.replace(" ", "_")
            assert (out / f"base_combo_{safe}.csv").exists(), safe

        # Base envelope summary exists.
        benv_csv = out / "base_envelope_summary.csv"
        assert benv_csv.exists(), "base_envelope_summary.csv not written"
        benv = pd.read_csv(benv_csv, encoding="utf-8")
        assert set(benv.columns) >= {"point", "load_name", "F3_min", "F3_max"}

        # Separated MIN/MAX envelope files exist with the correct schema.
        from etabs_extractor.models import BASE_FORCE_COLS
        benv_min = pd.read_csv(out / "base_envelope_min.csv", encoding="utf-8")
        benv_max = pd.read_csv(out / "base_envelope_max.csv", encoding="utf-8")
        assert list(benv_min.columns) == (["point", "load_name"] +
                                          [f"{c}_min" for c in BASE_FORCE_COLS]), \
            list(benv_min.columns)
        assert list(benv_max.columns) == (["point", "load_name"] +
                                          [f"{c}_max" for c in BASE_FORCE_COLS]), \
            list(benv_max.columns)
        # For a known synthetic point/load verify min/max semantics.  Point 1
        # with ASD 1 has (F1,F2,F3)=(10,2,120) and LRFD 1 has (15,3,180)
        # (source N), so after conversion to kN the combined 1/load_name
        # group min/max per component must match the ÷1000 values.
        pt1_asd = benv_min[(benv_min["point"].astype(str) == "1") &
                           (benv_min["load_name"] == "ASD 1")]
        assert len(pt1_asd) == 1, pt1_asd
        assert pt1_asd.iloc[0]["F3_min"] == 0.120
        pt1_all = benv_max[benv_max["point"].astype(str) == "1"]
        # Across ASD 1 (F3=120) and LRFD 1 (F3=180): max F3 in kN is 0.180.
        assert pt1_all["F3_max"].max() >= 0.180

        # Tagged base run: every base CSV and figure filename carries the suffix.
        tagged_dir = out / "tagged"
        _, _tp, _tr = extract_base_reactions(
            "synthetic_model.$et", str(tagged_dir),
            session=session,
            all_requested=False,
            tag="KH13",
        )
        assert (tagged_dir / "all_base_reactions_KH13.csv").exists()
        assert (tagged_dir / "base_envelope_min_KH13.csv").exists()
        assert (tagged_dir / "base_envelope_max_KH13.csv").exists()
        assert (tagged_dir / "base_envelope_summary_KH13.csv").exists()
        for c in combos:
            safe = c.replace(" ", "_")
            assert (tagged_dir / f"base_combo_{safe}_KH13.csv").exists(), c
        # Untagged legacy names must NOT appear alongside the tagged ones.
        assert not (tagged_dir / "all_base_reactions.csv").exists()
        assert not (tagged_dir / "base_envelope_min.csv").exists()
        # A whitespace-only tag behaves as no tag (no suffix).
        ws_dir = out / "wstag"
        _, _, _r2 = extract_base_reactions(
            "synthetic_model.$et", str(ws_dir),
            session=session, all_requested=False, tag="   ",
        )
        assert (ws_dir / "all_base_reactions.csv").exists()
        assert not (ws_dir / "all_base_reactions___.csv").exists()

        # Tagged frame run too (suffix applies to all outputs).
        _, _, _fr = extract_forces(
            "synthetic_model.$et", str(tagged_dir),
            session=session, all_requested=False, tag="KH13",
        )
        assert (tagged_dir / "all_forces_KH13.csv").exists()
        assert (tagged_dir / "envelope_summary_KH13.csv").exists()
        for c in combos:
            safe = c.replace(" ", "_")
            assert (tagged_dir / f"combo_{safe}_KH13.csv").exists(), c
        # Tagged plot figures.
        from etabs_extractor.plots import plot_base_reactions
        tg_plot = plot_base_reactions(bdf, tagged_dir, tag="KH13")
        for c in combos:
            safe = c.replace(" ", "_")
            p = tagged_dir / f"base_{safe}_plan_KH13.png"
            assert p.exists() and p.stat().st_size > 0, p


        # Points filter path sanity.
        bdf2, _bper2, brecs2 = extract_base_reactions(
            "synthetic_model.$et", str(out),
            session=session,
            points=["1"],
        )
        assert set(bdf2["point"].unique()) == {"1"}, set(bdf2["point"].unique())
        assert len(brecs2) == sum(1 for r in _REACT_BY_POINT["1"] if r["load"] in combos)

        # Elevation filter path sanity: only point 3 (coords 6000,3000,3000)
        # sits at z=3000, so an elevation filter must keep only its rows.
        bdf3, _bper3, brecs3 = extract_base_reactions(
            "synthetic_model.$et", str(out),
            session=session,
            elevation=3000.0,
        )
        assert len(bdf3) > 0, "elevation filter produced no rows"
        assert set(bdf3["z"].unique()) == {3000.0}, set(bdf3["z"].unique())
        assert set(bdf3["point"].unique()) == {"3"}, set(bdf3["point"].unique())
        expected_z3 = [r for r in _REACT_BY_POINT["3"] if r["load"] in combos]
        assert len(brecs3) == len(expected_z3), (len(brecs3), len(expected_z3))

        # Elevation filter that matches nothing returns no rows.
        bdf_none, _bnone, brecs_none = extract_base_reactions(
            "synthetic_model.$et", str(out),
            session=session,
            elevation=9999.0,
        )
        assert len(bdf_none) == 0 and len(brecs_none) == 0, "elevation miss not empty"

        # only_loaded filter: drop all-zero supports.  Point 4 carries no load
        # at all, so it must be removed; points 1-3 (all nonzero) stay.
        full_pts = set(bdf["point"].unique())
        assert "4" in full_pts, "fixture should include the zero-load point"
        bol, _bper_ol, brecs_ol = extract_base_reactions(
            "synthetic_model.$et", str(out),
            session=session,
            only_loaded=True,
        )
        assert set(bol["point"].unique()) == {"1", "2", "3"}, set(bol["point"].unique())
        expected_ol = [r for r in brecs if r.point != "4"]
        assert len(brecs_ol) == len(expected_ol), (len(brecs_ol), len(expected_ol))

        # ---- Plot path (headless, no COM) -----------------------------------
        from etabs_extractor.plots import (
            DEFAULT_COMPONENTS,
            plot_base_reactions,
            plot_base_reactions_from_csv,
        )

        # Default components are exactly Fz, M2, M3 (Fx/Fy omitted).
        assert DEFAULT_COMPONENTS == ("Fz", "M2", "M3"), DEFAULT_COMPONENTS

        # Unit conversion: base reactions are exported in kN/kN·m, so in BOTH
        # unit systems force/moment scale is identity (1.0); only the
        # coordinate length_scale differs (mm vs m).
        from etabs_extractor.plots import UNITS
        assert UNITS["kN-m"]["force_scale"] == 1.0
        assert UNITS["kN-m"]["moment_scale"] == 1.0
        assert UNITS["kN-m"]["length_scale"] == 1000.0
        assert UNITS["model"]["force_scale"] == 1.0
        assert UNITS["model"]["moment_scale"] == 1.0
        assert UNITS["model"]["length_scale"] == 1.0

        # Plot with kN/m units; still one figure per load, files non-empty.
        plot_paths_knm = plot_base_reactions(bdf, out, units="kN-m")
        assert len(plot_paths_knm) == len(combos), (len(plot_paths_knm), len(combos))
        for c in combos:
            safe = c.replace(" ", "_")
            p = out / f"base_{safe}_plan.png"
            assert p.exists() and p.stat().st_size > 0, p

        # Unknown unit system must raise a clear error.
        raised = False
        try:
            plot_base_reactions(bdf, out, units="bogus")
        except ValueError:
            raised = True
        assert raised, "expected ValueError for unknown units"

        # Plot the consolidated base DataFrame: one PNG per load name.
        plot_paths = plot_base_reactions(bdf, out)
        assert len(plot_paths) == len(combos), (len(plot_paths), len(combos))
        for c in combos:
            safe = c.replace(" ", "_")
            p = out / f"base_{safe}_plan.png"
            assert p in plot_paths, f"{p} not in {plot_paths}"
            assert p.exists(), f"{p} not written"
            assert p.stat().st_size > 0, f"{p} is empty"

        # Single-load plotting: only that combo's figure is produced.
        single = plot_base_reactions(bdf, out, load_name=combos[0])
        assert len(single) == 1, single
        safe0 = combos[0].replace(" ", "_")
        assert (out / f"base_{safe0}_plan.png") in single, single

        # CSV-driven path (no model/COM): writing the CSV then replotting it
        # must produce the same per-load figure set.
        csv_paths = plot_base_reactions_from_csv(all_base_csv, out)
        assert len(csv_paths) == len(combos), (len(csv_paths), len(combos))
        for c in combos:
            safe = c.replace(" ", "_")
            assert (out / f"base_{safe}_plan.png").exists()

        # NaN-coordinate rows must be skipped, never crash.  Build a fixture
        # DataFrame carrying one point with x=None (kept as NaN) alongside a
        # healthy point, and confirm the figure is still written.
        nan_df = pd.DataFrame(
            [
                {"point": "ok", "x": 0.0, "y": 0.0, "z": 0.0,
                 "load_name": "NA", "load_kind": "COMBO",
                 "F1": 1.0, "F2": 2.0, "F3": 3.0, "M1": 0.0, "M2": 1.0, "M3": 2.0},
                {"point": "bad", "x": None, "y": None, "z": None,
                 "load_name": "NA", "load_kind": "COMBO",
                 "F1": 0.0, "F2": 0.0, "F3": 0.0, "M1": 0.0, "M2": 0.0, "M3": 0.0},
            ]
        )
        nan_paths = plot_base_reactions(nan_df, out, load_name="NA")
        assert len(nan_paths) == 1, nan_paths
        assert (out / "base_NA_plan.png").exists()

        # Envelope-load aggregation: a point with two rows (Max/Min) must
        # collapse to one value per component — the largest absolute value,
        # sign preserved — and the point name must survive aggregation.
        # Values are unit-agnostic here (aggregation is pure max-abs); they
        # use kN-scale magnitudes to stay consistent with the new export units.
        from etabs_extractor.plots import _aggregate_maxabs
        env_df = pd.DataFrame([
            {"point": "7", "x": 100.0, "y": 200.0, "F1": 1.0, "F2": 2.0, "F3": 615.7599,
             "M1": 0.0, "M2": 10.0, "M3": 20.0, "load_name": "ENV"},
            {"point": "7", "x": 100.0, "y": 200.0, "F1": 3.0, "F2": 4.0, "F3": -304.458,
             "M1": 0.0, "M2": -15.0, "M3": 25.0, "load_name": "ENV"},
        ])
        agg = _aggregate_maxabs(env_df, ("Fz", "M2", "M3"))
        assert len(agg) == 1, f"expected 1 aggregated row, got {len(agg)}"
        first = agg.iloc[0]
        assert first["F3"] == 615.7599, first["F3"]
        assert first["M2"] == -15.0, first["M2"]
        assert first["M3"] == 25.0, first["M3"]
        # Point name preserved across the (x,y) group merge.
        assert "point" in agg.columns, agg.columns
        assert str(first["point"]) == "7", first["point"]

        # Label formatting: the first line is the bare point name.
        from etabs_extractor.plots import _format_label, UNITS
        label = _format_label(agg.iloc[0], ("Fz", "M2", "M3"), UNITS["model"])
        label_lines = label.split("\n")
        assert label_lines[0] == "7", label_lines
        # Units: base reactions are exported in kN/kN·m, so labels under BOTH
        # unit systems carry "kN" / "kN·m" (model => coords mm).
        for system in ("model", "kN-m"):
            lbl = _format_label(agg.iloc[0], ("Fz", "M2", "M3"), UNITS[system])
            assert "kN" in lbl, (system, lbl)
            assert "kN·m" in lbl, (system, lbl)
        # A null point name is omitted defensively (no blank first line).
        null_label = _format_label(
            {"point": None, "F3": 1.0, "M2": 0.0, "M3": 0.0},
            ("Fz",), UNITS["model"],
        )
        assert null_label.split("\n")[0].startswith("Fz="), null_label


        # Plain (non-scientific) label formatting must not emit 1e+04.
        from etabs_extractor.plots import _fmt_plain
        assert _fmt_plain(10000.0) == "10000"
        assert _fmt_plain(615760.0) == "615760"
        assert _fmt_plain(7.18) == "7.18"
        assert "e+" not in _fmt_plain(123456789.0)

        print(f"Dry run OK: {len(df)} combo rows, {len(combos)} combo CSVs, "
              f"all_forces.csv={len(csv_df)} rows, envelope={len(env)} rows; "
              f"base={len(bdf)} reaction rows, {len(base_combo_files)} base CSVs; "
              f"plots={len(plot_paths)} plan figures.")
        print("PASSED")


if __name__ == "__main__":
    run()