"""etabs_extractor — extract frame-element forces from ETABS via the COM API.

Drives ETABS 22 through its COM interface to read frame internal forces
(axial ``P``, shears ``V2``/``V3``, torsion ``T``, moments ``M2``/``M3``) from
a model's load combinations (and optionally load cases), and emits the
results to CSV while also returning them as pandas DataFrames.

Only attribute imports that do **not** require a Windows/COM runtime live at
package top-level.  The heavy COM machinery is imported lazily inside the
connection module so that the pure-Python parts (models, io, config) remain
importable and testable on any platform (e.g. WSL/Linux for the dry run).
"""

from .config import (
    DEFAULT_COM_PROGID,
    DEFAULT_MODEL_VARIABLE,
    DEFAULT_OUTPUT_VARIABLE,
    DEFAULT_OUTPUT_DIR,
    resolve_model_path,
    resolve_output_dir,
)
from .models import (
    FrameForceRecord,
    JointReactionRecord,
    summarize_base_envelope_minmax,
    to_base_dataframe,
    to_dataframe,
)
from .io import (
    write_all_base_csv,
    write_all_forces_csv,
    write_base_csv,
    write_base_envelope_csv,
    write_base_envelope_max_csv,
    write_base_envelope_min_csv,
    write_csv,
)
from .plots import (
    COMPONENT_COLUMNS,
    COMPONENT_UNITS,
    DEFAULT_COMPONENTS,
    DEFAULT_UNITS,
    UNITS,
    build_base_reactions_figure,
    plot_base_reactions,
    plot_base_reactions_from_csv,
)
from .results import extract_base_reactions, extract_forces, list_available

__all__ = [
    "DEFAULT_COM_PROGID",
    "DEFAULT_MODEL_VARIABLE",
    "DEFAULT_OUTPUT_VARIABLE",
    "DEFAULT_OUTPUT_DIR",
    "resolve_model_path",
    "resolve_output_dir",
    "FrameForceRecord",
    "JointReactionRecord",
    "to_dataframe",
    "to_base_dataframe",
    "summarize_base_envelope_minmax",
    "write_csv",
    "write_all_forces_csv",
    "write_base_csv",
    "write_all_base_csv",
    "write_base_envelope_csv",
    "write_base_envelope_min_csv",
    "write_base_envelope_max_csv",
    "DEFAULT_COMPONENTS",
    "COMPONENT_COLUMNS",
    "COMPONENT_UNITS",
    "DEFAULT_UNITS",
    "UNITS",
    "plot_base_reactions",
    "plot_base_reactions_from_csv",
    "build_base_reactions_figure",
    "extract_forces",
    "extract_base_reactions",
    "list_available",
]

__version__ = "0.1.0"
