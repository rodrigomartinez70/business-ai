"""
Importación de datos vía CSV.

POST /api/ingest/{tabla}?modo=validar  — dry-run: valida sin escribir
POST /api/ingest/{tabla}?modo=insertar — inserta en transacción (rollback total si falla)

Requiere INGEST_DATABASE_URL configurada con un usuario que tenga permisos INSERT.
"""

import csv
import io
from datetime import date as DateType
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from .. import config
from ..auth import get_role

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


async def _primary_key_columns(tabla: str) -> list[str]:
    rows = await config.db_pool.fetch("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
           AND tc.table_schema    = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema    = 'public'
          AND tc.table_name      = $1
        ORDER BY kcu.ordinal_position
    """, tabla)
    return [r["column_name"] for r in rows]


async def _tablas_permitidas() -> frozenset[str]:
    """Tablas de negocio disponibles para importación (excluye infraestructura interna)."""
    exclude = set(config.CONFIG.get("schema", {}).get("exclude_tables", []))
    rows = await config.db_pool.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    return frozenset(r["table_name"] for r in rows if r["table_name"] not in exclude)


async def _columnas_insertables(tabla: str) -> list[dict]:
    """
    Devuelve las columnas que el usuario puede proveer en el CSV, con sus tipos.
    Excluye: SERIAL (nextval), GENERATED ALWAYS AS, created_at.
    """
    rows = await config.db_pool.fetch(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = $1
          AND is_generated = 'NEVER'
          AND (column_default IS NULL OR column_default NOT LIKE 'nextval%%')
          AND column_name  != 'created_at'
        ORDER BY ordinal_position
        """,
        tabla,
    )
    return [{"name": r["column_name"], "type": r["data_type"]} for r in rows]


def _convertir_valor(valor: Optional[str], pg_type: str) -> Any:
    """Convierte el string del CSV al tipo Python que espera asyncpg."""
    if valor is None or valor == "":
        return None
    pg_type = pg_type.lower()
    try:
        if pg_type in ("date",):
            return DateType.fromisoformat(valor)
        if pg_type in ("numeric", "decimal", "real", "double precision", "money"):
            return Decimal(valor)
        if pg_type in ("integer", "bigint", "smallint", "int", "int4", "int8", "int2"):
            return int(valor)
        if pg_type in ("boolean", "bool"):
            return valor.lower() in ("true", "t", "yes", "1", "si", "sí")
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"No se pudo convertir '{valor}' a tipo {pg_type}: {exc}") from exc
    return valor


def _leer_csv(contenido: bytes) -> tuple[list[str], list[dict]]:
    """Decodifica y parsea el CSV. Soporta UTF-8 BOM (exportaciones de Excel) y Latin-1."""
    texto = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = contenido.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if texto is None:
        raise HTTPException(status_code=400, detail="No se pudo decodificar el archivo CSV.")

    reader = csv.DictReader(io.StringIO(texto))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV vacío o sin encabezados.")

    cols  = [c.strip().lower() for c in reader.fieldnames]
    filas = [
        {c.strip().lower(): (v.strip() or None) for c, v in row.items()}
        for row in reader
    ]

    if not filas:
        raise HTTPException(status_code=400, detail="El CSV no contiene filas de datos.")

    return cols, filas


@router.get("/tablas")
async def listar_tablas(_rol: str = Depends(get_role)):
    """Lista las tablas disponibles para importación."""
    tablas = await _tablas_permitidas()
    return {"tablas": sorted(tablas)}


@router.post("/{tabla}")
async def importar_csv(
    tabla:   str,
    archivo: UploadFile = File(..., description="Archivo CSV a importar"),
    modo:    str        = Query("validar", description="validar (dry-run) | insertar | upsert"),
    _rol:    str        = Depends(get_role),
):
    """
    Importa datos desde un CSV a la tabla indicada.

    **Modos:**
    - `validar` — preview sin escribir: muestra columnas reconocidas, ignoradas y primeras 3 filas.
    - `insertar` — inserta en una transacción. Si falla alguna fila, rollback total e informe de error.
    - `upsert`   — INSERT ... ON CONFLICT DO UPDATE usando la clave primaria de la tabla. Idempotente.

    **Reglas del CSV:**
    - Primera fila: nombres de columna (case-insensitive).
    - Columnas auto-generadas (`id`, `noches`, `total`, `margen`, etc.) se ignoran automáticamente.
    - Celdas vacías se tratan como NULL.
    - Separador: coma. Codificación: UTF-8, UTF-8 BOM o Latin-1.
    """
    tablas_permitidas = await _tablas_permitidas()
    if tabla not in tablas_permitidas:
        raise HTTPException(
            status_code=400,
            detail=f"Tabla '{tabla}' no permitida. Disponibles: {sorted(tablas_permitidas)}",
        )

    cols_db = await _columnas_insertables(tabla)
    if not cols_db:
        raise HTTPException(status_code=404, detail=f"Tabla '{tabla}' no encontrada en la DB.")

    cols_db_map = {c["name"]: c["type"] for c in cols_db}

    contenido          = await archivo.read()
    cols_csv, filas    = _leer_csv(contenido)
    cols_validas       = [c for c in cols_csv if c in cols_db_map]
    cols_ignoradas     = [c for c in cols_csv if c not in cols_db_map]

    if not cols_validas:
        raise HTTPException(
            status_code=400,
            detail={
                "error":     "Ninguna columna del CSV coincide con la tabla.",
                "csv":       cols_csv,
                "esperadas": list(cols_db_map.keys()),
            },
        )

    filas_proyectadas = [{c: f.get(c) for c in cols_validas} for f in filas]

    if modo == "validar":
        return {
            "modo":               "validar",
            "tabla":              tabla,
            "columnas_validas":   cols_validas,
            "columnas_ignoradas": cols_ignoradas,
            "filas_a_insertar":   len(filas_proyectadas),
            "preview":            filas_proyectadas[:3],
        }

    # ── modos insertar / upsert ───────────────────────────────
    if config.ingest_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Ingest no configurado. Definir INGEST_DATABASE_URL en .env.",
        )

    cols_str     = ", ".join(cols_validas)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols_validas)))

    if modo == "upsert":
        pk_cols = await _primary_key_columns(tabla)
        if not pk_cols:
            raise HTTPException(
                status_code=400,
                detail=f"La tabla '{tabla}' no tiene clave primaria — UPSERT no es posible.",
            )
        update_cols = [c for c in cols_validas if c not in pk_cols]
        if not update_cols:
            raise HTTPException(
                status_code=400,
                detail="Sin columnas a actualizar — todas las columnas del CSV son clave primaria.",
            )
        conflict = ", ".join(pk_cols)
        updates  = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        query = (
            f"INSERT INTO {tabla} ({cols_str}) VALUES ({placeholders})"
            f" ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
        )
    else:
        query = f"INSERT INTO {tabla} ({cols_str}) VALUES ({placeholders})"

    async with config.ingest_pool.acquire() as conn:
        async with conn.transaction():
            for i, fila in enumerate(filas_proyectadas):
                try:
                    valores = [
                        _convertir_valor(fila[c], cols_db_map[c])
                        for c in cols_validas
                    ]
                    await conn.execute(query, *valores)
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error":    f"Error en fila {i + 2}: {exc}",
                            "fila":     i + 2,
                            "datos":    fila,
                            "rollback": f"Se deshicieron las {i} filas anteriores.",
                        },
                    )

    return {
        "modo":               modo,
        "tabla":              tabla,
        "filas_procesadas":   len(filas_proyectadas),
        "columnas_ignoradas": cols_ignoradas,
    }
