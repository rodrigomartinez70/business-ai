"""Packs de datos componibles. Ver `doc/design-packs.md`."""

from .registry import (  # noqa: F401
    PACKS, VERTICAL_PACKS, Pack, PackError,
    catalogo, cargar_packs, existe, normalizar,
    packs_de_vertical, schema_ddl,
)
