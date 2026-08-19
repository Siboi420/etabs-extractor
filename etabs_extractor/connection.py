"""COM connection to a running/launched ETABS 22 instance.

This module is the only place that imports the Windows COM machinery
(comtypes).  All imports here are done lazily inside functions so that the
rest of the package remains importable (and testable) on non-Windows
platforms like WSL/Linux.

Usage is Windows-interpreter-only: ETABS must be installed and the COM
server registered.  Two connection strategies are supported:

* ``attach`` — connect to an already-running ETABS via ``GetActiveObject``.
* ``launch``  — create/find an ETABS helper and start the application.

After a connection is obtained, :func:`connect` returns a small wrapper
around the ``SapModel`` object exposing the handful of operations the
extractor needs, with a minimal, duck-typed surface so tests can substitute
a fake.
"""

from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING, Any

from .config import DEFAULT_COM_PROGID, to_windows_path

if TYPE_CHECKING:
    from pathlib import Path


class EtabsConnectionError(RuntimeError):
    """Raised when ETABS COM cannot be attached/launched or used."""


# The concrete SapModel type only exists on Windows with comtypes present;
# we keep it as a protocol-ish Any here and import comtypes lazily.
def _comtypes():
    try:
        import comtypes  # noqa: PLC0415
        import comtypes.client  # noqa: PLC0415
        return comtypes
    except ImportError as exc:  # pragma: no cover - controlled path
        raise EtabsConnectionError(
            "comtypes is required for ETABS COM access. Install it on a "
            "Windows Python interpreter (pip install comtypes)."
        ) from exc


def _etabs_progid(version_hint: str | None = None) -> str:
    """Return the COM ProgID for ETABS based on an optional version hint.

    ``version_hint`` is accepted for forward-compatibility (e.g. "23"); the
    default targets the ``ETABSv1`` registered helper ProgID.
    """
    return DEFAULT_COM_PROGID


def _c_helper(comtypes):
    """Return the typed ``cHelper`` interface class from the generated
    ``comtypes.gen.ETABSv1`` module, generating it if needed.

    The CSI typelib (``ETABSv1.tlb``) is registered with the installed app;
    ``GetModule`` by ProgID auto-discovers and generates the comtypes
    wrapper on first call, then we re-import it on later calls.
    """
    try:
        # Already generated earlier in this process?  comtypes.gen modules are
        # dynamic (generated at runtime) so we load them via importlib.
        et = importlib.import_module("comtypes.gen.ETABSv1")
        if hasattr(et, "cHelper"):
            return et.cHelper
    except Exception:  # noqa: BLE001
        # Not generated yet — fall through and generate below.
        pass

    from comtypes.client import GetModule  # noqa: PLC0415

    GetModule(DEFAULT_COM_PROGID)  # "ETABSv1.Helper"
    et = importlib.import_module("comtypes.gen.ETABSv1")
    return et.cHelper


def _ensure_comtypes_wrapper_available() -> None:
    """Force-cache the generated comtypes wrapper so COM calls resolve."""
    import comtypes  # noqa: PLC0415

    progid = _etabs_progid()
    try:
        # Register the type library in comtypes' generated cache.
        from comtypes.client import GetModule  # noqa: PLC0415

        GetModule(progid)
    except Exception:  # noqa: BLE001  pragma: no cover
        # ProgID may already be cached here; non-fatal, nothing to do.
        pass


class EtabsSession:
    """Thin, duck-typed wrapper over a connected ``SapModel``.

    Only the operations the extractor needs are surfaced, keeping tests
    (which pass a fake with the same methods) faithful.
    """

    def __init__(
        self,
        helper: Any,
        sap_model: Any,
        *,
        progid: str = DEFAULT_COM_PROGID,
    ) -> None:
        self.helper = helper
        self.sap_model = sap_model
        self.progid = progid

    # -- Connection lifecycle ------------------------------------------------

    @classmethod
    def connect(
        cls,
        *,
        attach: bool = True,
        launch: bool = False,
        model_path: str | None = None,
        version_hint: str | None = None,
    ) -> "EtabsSession":
        """Attach to (or launch) ETABS and optionally open a model.

        Uses the typed CSI OAPI connection sequence (``ETABSv1.Helper`` ->
        QueryInterface ``cHelper`` -> ``GetObject("CSI.ETABS.API.ETABSObject")``
        -> ``SapModel``).  This requires the ``ETABSv1`` comtypes typelib,
        which is auto-generated from the installed type library on first use.

        :param attach:  if True, try to connect to an active ETABS instance.
        :param launch:  if True and no active instance, start ETABS.
        :param model_path: optional model (``.et``/``.EDB``) to open via
            ``File.OpenFile`` (converted to a Windows path first).
        :param version_hint: optional ETABS major-version hint (unused; the
            typelib is discovered from the COM registration).
        :returns: an :class:`EtabsSession`.
        :raises EtabsConnectionError: on any COM failure.
        """
        comtypes = _comtypes()

        cHelper = _c_helper(comtypes)
        try:
            helper = comtypes.client.CreateObject(_etabs_progid(version_hint))
            helper = helper.QueryInterface(cHelper)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(
                f"Could not create ETABS Helper (is ETABS installed/registered?): {exc}"
            ) from exc

        # GetObject returns the cOAPI that the running ETABS exposes.  With
        # ``attach`` we expect an instance to already exist; with ``launch``
        # ETABS is started on demand by the LocalServer32 registration.
        try:
            etabs_obj = helper.GetObject("CSI.ETABS.API.ETABSObject")
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(
                "Could not obtain the ETABS cOAPI object. Ensure ETABS is "
                "running (or pass `launch=True`)."
            ) from exc

        # Proceed to the SapModel interface.
        try:
            sap_model = etabs_obj.SapModel
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"Could not reach SapModel: {exc}") from exc

        session = cls(helper=etabs_obj, sap_model=sap_model)

        if model_path:
            session.open_model(model_path)

        return session

    def open_model(self, model_path: str | os.PathLike) -> None:
        """Open a model file, translating POSIX ``/mnt/...`` to Windows paths."""
        win_path = to_windows_path(str(model_path))
        try:
            ret = self.sap_model.File.OpenFile(win_path)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"File.OpenFile failed: {exc}") from exc
        if ret not in (0, None):
            raise EtabsConnectionError(
                f"File.OpenFile returned non-zero status {ret!r} for {win_path!r}"
            )

    def run_analysis(self) -> None:
        """Run a full static/nonlinear analysis via ``Analyze.RunAnalysis``."""
        try:
            ret = self.sap_model.Analyze.RunAnalysis()
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"Analyze.RunAnalysis failed: {exc}") from exc
        if ret not in (0, None):
            raise EtabsConnectionError(f"Analyze.RunAnalysis returned {ret!r}")

    # -- Introspection used by the extractor ---------------------------------

    def get_frame_names(self) -> list[str]:
        """Return the list of frame object names in the model."""
        try:
            count, names = _gp(self.sap_model.FrameObj.GetNameList)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"FrameObj.GetNameList failed: {exc}") from exc
        return list(names or [])

    def get_combo_names(self) -> list[str]:
        """Return the list of response combination names."""
        try:
            count, names = _gp(self.sap_model.RespCombo.GetNameList)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"RespCombo.GetNameList failed: {exc}") from exc
        return list(names or [])

    def get_case_names(self) -> list[str]:
        """Return the list of load case names."""
        try:
            count, names = _gp(self.sap_model.LoadCases.GetNameList)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"LoadCases.GetNameList failed: {exc}") from exc
        return list(names or [])

    def get_section_for_frame(self, frame: str) -> str:
        try:
            # comtypes returns [SectionName, ...rest, retcode]; name is first.
            out = self.sap_model.FrameObj.GetSection(frame)
            if isinstance(out, (list, tuple)) and out:
                # Find the first non-empty string element (the section name).
                for elem in out:
                    if isinstance(elem, str) and elem.strip():
                        return elem
            if isinstance(out, str):
                return out
        except Exception:  # noqa: BLE001
            # Section lookup is best-effort; a failure just yields no section.
            pass
        return ""

    def setup_select_combos(self, combos: list[str] | None) -> None:
        """Select only ``combos`` for output; deselect everything else."""
        setup = self.sap_model.Results.Setup
        setup.DeselectAllCasesAndCombosForOutput()
        for c in combos or []:
            setup.SetComboSelectedForOutput(c, True)

    def setup_select_cases(self, cases: list[str] | None) -> None:
        """Select only ``cases`` for output; deselect everything else."""
        setup = self.sap_model.Results.Setup
        setup.DeselectAllCasesAndCombosForOutput()
        for c in cases or []:
            setup.SetCaseSelectedForOutput(c, True)

    # -- Base (joint) reaction reads -----------------------------------------

    def get_point_names(self) -> list[str]:
        """Return the list of point (joint) object names in the model."""
        try:
            count, names = _gp(self.sap_model.PointObj.GetNameList)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(f"PointObj.GetNameList failed: {exc}") from exc
        return list(names or [])

    def get_point_coords(self, point: str) -> tuple[float | None, float | None, float | None]:
        """Return the global ``(x, y, z)`` coordinates of a point object.

        ``z`` is the elevation.  Values are null-safe-coerced to ``float``;
        a point with no resolvable coordinates returns ``None`` slots.
        """
        try:
            out = self.sap_model.PointObj.GetCoordCartesian(point)
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(
                f"PointObj.GetCoordCartesian failed for {point!r}: {exc}"
            ) from exc
        if not isinstance(out, (list, tuple)):
            return (None, None, None)
        # comtypes returns [X, Y, Z, retcode]; coordinate slots are first.
        x = _f_coord(out, 0)
        y = _f_coord(out, 1)
        z = _f_coord(out, 2)
        return (x, y, z)

    def joint_react(
        self,
        point: str,
        item_type_elm: int = 0,
    ) -> tuple[list, ...] | None:
        """Call ``Results.JointReact`` and return the output arrays.

        The comtypes-generated wrapper returns a list where the first element
        is ``NumberResults`` and the following elements are the by-reference
        output arrays in the API's parameter order:

        ``[NumberResults, Obj, Elm, LoadCase, StepType, StepNum, F1, F2, F3,
           M1, M2, M3, retcode]``

        Returns ``None`` when ``NumberResults == 0`` (known COM quirk), else
        that 12-tuple of arrays (retcode dropped):
        ``(NumberResults, Obj, Elm, LoadCase, StepType, StepNum, F1, F2, F3,
        M1, M2, M3)``.
        """
        sap = self.sap_model
        # Pass empty output containers; comtypes fills and returns them.
        out = sap.Results.JointReact(
            point,
            item_type_elm,
            0,
            [], [], [], [], [], [], [], [], [], [], [],
        )
        if out is None or not isinstance(out, (list, tuple)):
            raise EtabsConnectionError(
                f"JointReact returned an unexpected value for {point!r}: {out!r}"
            )

        n = len(out)
        NumberResults = out[0] if n > 0 else 0
        if not NumberResults:
            return None

        def _seg(i):
            return out[i] if n > i else []

        return (
            NumberResults,
            _seg(1), _seg(2), _seg(3), _seg(4), _seg(5), _seg(6),
            _seg(7), _seg(8), _seg(9), _seg(10), _seg(11),
        )

    def frame_force(
        self,
        frame: str,
        item_type_elm: int = 0,
    ) -> tuple[list, ...] | None:
        """Call ``Results.FrameForce`` and return the output arrays.

        The comtypes-generated wrapper returns a list where the first element
        is ``NumberResults`` and the following elements are the by-reference
        output arrays in the API's parameter order:

        ``[NumberResults, Obj, ObjSta, Elm, ElmSta, LoadCase, StepType,
           StepNum, P, V2, V3, T, M2, M3, retcode]``

        Returns ``None`` when ``NumberResults == 0`` (known COM quirk), else
        that 14-tuple of arrays (retcode dropped).
        """
        sap = self.sap_model
        # Pass empty output containers; comtypes fills and returns them.
        out = sap.Results.FrameForce(
            frame,
            item_type_elm,
            0,
            [], [], [], [], [], [], [], [], [], [], [], [], [],
        )
        if out is None or not isinstance(out, (list, tuple)):
            raise EtabsConnectionError(
                f"FrameForce returned an unexpected value for {frame!r}: {out!r}"
            )

        n = len(out)
        NumberResults = out[0] if n > 0 else 0
        if not NumberResults:
            return None

        def _seg(i):
            return out[i] if n > i else []

        return (
            NumberResults,
            _seg(1), _seg(2), _seg(3), _seg(4), _seg(5), _seg(6), _seg(7),
            _seg(8), _seg(9), _seg(10), _seg(11), _seg(12), _seg(13),
        )


def _gp(func) -> tuple[int | None, list]:
    """Call a ``GetNameList``-style COM method.

    The comtypes-generated wrapper returns a sequence like
    ``[count, (name1, name2, ...), retcode]``.  We return ``(count, names)``.
    """
    out = func(0, [])
    if not isinstance(out, (list, tuple)) or len(out) < 2:
        return (None, [])
    count = out[0]
    names = list(out[1] or [])
    return count, names


def _f_coord(seq, i) -> float | None:
    """Null-safe coercion of a coordinate slot to ``float`` or ``None``.

    COM output arrays may contain ``None`` or non-numeric placeholders for
    unavailable coordinates; those coerce to ``None`` (kept as ``NaN`` in the
    DataFrame) rather than raising.
    """
    if seq is None or i >= len(seq):
        return None
    try:
        val = seq[i]
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError, IndexError):
        return None


def _launch_etabs(comtypes) -> Any:
    """Start ETABS (COM server) and return a helper object."""
    try:
        helper = comtypes.client.CreateObject("CSI.ETABS.API.ETABSObject")
    except Exception:  # noqa: BLE001
        try:
            helper = comtypes.client.CreateObject(_etabs_progid())
        except Exception as exc:  # noqa: BLE001
            raise EtabsConnectionError(
                "Could not launch ETABS COM server. Verify ETABS is installed "
                "and registered for COM automation."
            ) from exc
    try:
        helper.ApplicationStart()
    except AttributeError:
        # Some interfaces start implicitly on first access; nothing to do.
        pass
    return helper
