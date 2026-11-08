"""CAD reader (Ticket 1.2): DXF directly, DWG through a converter.

Needs the ``cad`` extra (``ezdxf``) at call time; importing :mod:`ale.cad` imports
ezdxf only lazily, inside the readers.
"""

from __future__ import annotations

from ale.cad.convert import ConvertResult, convert_dwg
from ale.cad.layers import LayerMap, LayerRole, load_layer_map, propose_layer_map, save_layer_map
from ale.cad.read import CadReadResult, read_cad

__all__ = [
    "CadReadResult",
    "ConvertResult",
    "LayerMap",
    "LayerRole",
    "convert_dwg",
    "load_layer_map",
    "propose_layer_map",
    "read_cad",
    "save_layer_map",
]
