"""
Visor del modelo de datos (esquema) de cada tenant — solo lectura.

Lee el esquema vivo desde information_schema (tablas + columnas + PKs del schema
del tenant). No ejecuta SQL del usuario; es una previsualización del modelo.
"""

from .. import config


async def modelo(tenant_id: str) -> dict:
    cols = await config.raw_pool.fetch(
        """SELECT table_name, column_name, data_type, is_nullable, ordinal_position
             FROM information_schema.columns
            WHERE table_schema = $1
            ORDER BY table_name, ordinal_position""", tenant_id)
    pks = await config.raw_pool.fetch(
        """SELECT kcu.table_name, kcu.column_name
             FROM information_schema.table_constraints tc
             JOIN information_schema.key_column_usage kcu
               ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = $1 AND tc.constraint_type = 'PRIMARY KEY'""", tenant_id)
    pkset = {(r["table_name"], r["column_name"]) for r in pks}

    tablas: dict[str, list] = {}
    for c in cols:
        tablas.setdefault(c["table_name"], []).append({
            "nombre": c["column_name"],
            "tipo": c["data_type"],
            "nullable": c["is_nullable"] == "YES",
            "pk": (c["table_name"], c["column_name"]) in pkset,
        })
    return {
        "tenant_id": tenant_id,
        "n_tablas": len(tablas),
        "tablas": [{"nombre": t, "columnas": cs} for t, cs in sorted(tablas.items())],
    }
