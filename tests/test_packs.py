"""
Tests de los packs de datos componibles (P1).

El test clave es de EQUIVALENCIA: el ensamblado de los packs de un vertical debe
reproducir exactamente el conjunto de tablas del schema.sql histórico de ese
vertical. Esto garantiza que migrar el alta a packs no cambia el modelo de datos.
"""

import re
from pathlib import Path

import pytest

from src import packs as pk

_SRC = Path(pk.__file__).resolve().parent.parent        # .../api/src (ancla al paquete)

_RE_TABLA = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.IGNORECASE)


def _tablas(sql: str) -> set[str]:
    return {m.group(1).lower() for m in _RE_TABLA.finditer(sql)}


# Marketing es horizontal: históricamente vivía en postgres/marketing.sql y se
# aplicaba aparte a cada tenant. Ahora está en el pack base, así que la
# equivalencia es: packs == schema del vertical ∪ marketing.sql.
_MARKETING = _SRC.parent.parent / "postgres" / "marketing.sql"


def _tablas_vertical(vertical: str) -> set[str]:
    return (_tablas((_SRC / "verticals" / vertical / "schema.sql").read_text())
            | _tablas(_MARKETING.read_text()))


@pytest.mark.parametrize("vertical", ["restaurante", "hotel"])
def test_equivalencia_packs_vs_vertical(vertical):
    """base ∪ pos_* ∪ erp == tablas del schema.sql del vertical."""
    ddl = pk.schema_ddl(pk.packs_de_vertical(vertical))
    assert _tablas(ddl) == _tablas_vertical(vertical)


def test_packs_de_vertical():
    assert pk.packs_de_vertical("restaurante") == ["base", "pos_gastronomico", "erp"]
    assert pk.packs_de_vertical("hotel") == ["base", "pos_hotelero", "erp"]
    # Vertical desconocido → al menos base.
    assert pk.packs_de_vertical("fabrica") == ["base"]
    assert pk.packs_de_vertical(None) == ["base"]


def test_normalizar_agrega_base_y_ordena():
    # Pide erp sin base → base se agrega (prerequisito); orden canónico del catálogo.
    assert pk.normalizar(["erp"]) == ["base", "erp"]
    assert pk.normalizar(["erp", "pos_gastronomico"]) == ["base", "pos_gastronomico", "erp"]
    # Deduplica.
    assert pk.normalizar(["base", "base"]) == ["base"]


def test_normalizar_pack_desconocido():
    with pytest.raises(pk.PackError):
        pk.normalizar(["inexistente"])


def test_schema_ddl_idempotente():
    """Todo CREATE TABLE del ensamblado es IF NOT EXISTS (seguro de re-aplicar)."""
    ddl = pk.schema_ddl(["base", "pos_gastronomico", "pos_hotelero", "erp"])
    creates = re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+\w+", ddl, re.IGNORECASE)
    assert creates, "el ensamblado debe contener CREATE TABLE"
    assert all("IF NOT EXISTS" in c.upper() for c in creates)


def test_catalogo_tiene_los_cuatro_packs():
    ids = {p.id for p in pk.catalogo()}
    assert ids == {"base", "pos_gastronomico", "pos_hotelero", "erp"}


def test_cargar_packs_no_revienta():
    # No debe lanzar aunque algún módulo de fuentes no exista.
    pk.cargar_packs(["base", "erp"])
