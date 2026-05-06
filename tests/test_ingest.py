"""
Tests de importación CSV — POST /api/ingest/{tabla}

Estrategia de aislamiento:
  - Los tests de inserción usan el marcador TEST_ en el campo descripcion.
  - El fixture `cleanup_gastos` borra esas filas al finalizar el test.
"""

import io
import pytest
import pytest_asyncio

from src import config


CSV_GASTOS_VALIDO = b"""fecha,descripcion,monto,proveedor
2024-03-01,TEST_Limpieza mensual,45000,Proveedor X
2024-03-02,TEST_Suministros oficina,12500,Proveedor Y
"""

CSV_GASTOS_CON_COLUMNA_EXTRA = b"""fecha,descripcion,monto,columna_inventada,proveedor
2024-03-01,TEST_Con extra,30000,ignorame,Proveedor Z
"""

CSV_GASTOS_VACIO = b"fecha,descripcion,monto\n"

CSV_GASTOS_ID_SERIAL = b"""id,fecha,descripcion,monto
999,2024-03-01,TEST_Con id,10000
"""


@pytest_asyncio.fixture
async def cleanup_gastos():
    yield
    if config.ingest_pool:
        async with config.ingest_pool.acquire() as conn:
            await conn.execute("DELETE FROM gastos WHERE descripcion LIKE 'TEST_%'")


# ── Modo validar ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validar_csv_valido(client, gerente_headers):
    resp = await client.post(
        "/api/ingest/gastos?modo=validar",
        headers=gerente_headers,
        files={"archivo": ("gastos.csv", io.BytesIO(CSV_GASTOS_VALIDO), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["modo"] == "validar"
    assert data["tabla"] == "gastos"
    assert data["filas_a_insertar"] == 2
    assert "fecha" in data["columnas_validas"]
    assert "monto" in data["columnas_validas"]
    assert len(data["preview"]) == 2


@pytest.mark.asyncio
async def test_validar_columna_extra_se_ignora(client, gerente_headers):
    resp = await client.post(
        "/api/ingest/gastos?modo=validar",
        headers=gerente_headers,
        files={"archivo": ("gastos.csv", io.BytesIO(CSV_GASTOS_CON_COLUMNA_EXTRA), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "columna_inventada" in data["columnas_ignoradas"]
    assert "columna_inventada" not in data["columnas_validas"]


@pytest.mark.asyncio
async def test_validar_no_escribe_en_db(client, gerente_headers):
    """El modo validar no debe modificar la DB."""
    async with config.db_pool.acquire() as conn:
        antes = await conn.fetchval("SELECT COUNT(*) FROM gastos")

    await client.post(
        "/api/ingest/gastos?modo=validar",
        headers=gerente_headers,
        files={"archivo": ("gastos.csv", io.BytesIO(CSV_GASTOS_VALIDO), "text/csv")},
    )

    async with config.db_pool.acquire() as conn:
        despues = await conn.fetchval("SELECT COUNT(*) FROM gastos")

    assert antes == despues


@pytest.mark.asyncio
async def test_validar_csv_vacio_retorna_400(client, gerente_headers):
    resp = await client.post(
        "/api/ingest/gastos?modo=validar",
        headers=gerente_headers,
        files={"archivo": ("vacio.csv", io.BytesIO(CSV_GASTOS_VACIO), "text/csv")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_validar_columna_id_se_ignora(client, gerente_headers):
    """La columna 'id' (SERIAL) no debe aparecer en columnas_validas."""
    resp = await client.post(
        "/api/ingest/gastos?modo=validar",
        headers=gerente_headers,
        files={"archivo": ("gastos.csv", io.BytesIO(CSV_GASTOS_ID_SERIAL), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" not in data["columnas_validas"]
    assert "id" in data["columnas_ignoradas"]


# ── Modo insertar ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insertar_csv_valido(client, gerente_headers, cleanup_gastos):
    async with config.db_pool.acquire() as conn:
        antes = await conn.fetchval("SELECT COUNT(*) FROM gastos")

    resp = await client.post(
        "/api/ingest/gastos?modo=insertar",
        headers=gerente_headers,
        files={"archivo": ("gastos.csv", io.BytesIO(CSV_GASTOS_VALIDO), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["modo"] == "insertar"
    assert data["filas_procesadas"] == 2

    async with config.db_pool.acquire() as conn:
        despues = await conn.fetchval("SELECT COUNT(*) FROM gastos")
    assert despues == antes + 2


@pytest.mark.asyncio
async def test_insertar_fk_invalida_hace_rollback(client, gerente_headers):
    """Una reserva_id inexistente debe fallar y hacer rollback de todo."""
    csv_invalido = b"reserva_id,fecha,descripcion,cantidad,precio_unitario,costo_unitario\n999999,2024-03-01,TEST item,1,100,50\n"

    async with config.db_pool.acquire() as conn:
        antes = await conn.fetchval("SELECT COUNT(*) FROM consumos_frigobar")

    resp = await client.post(
        "/api/ingest/consumos_frigobar?modo=insertar",
        headers=gerente_headers,
        files={"archivo": ("consumos.csv", io.BytesIO(csv_invalido), "text/csv")},
    )
    assert resp.status_code == 422
    assert "rollback" in resp.json()["detail"]

    async with config.db_pool.acquire() as conn:
        despues = await conn.fetchval("SELECT COUNT(*) FROM consumos_frigobar")
    assert antes == despues  # rollback confirmado


# ── Listado de tablas ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_tablas(client, gerente_headers):
    resp = await client.get("/api/ingest/tablas", headers=gerente_headers)
    assert resp.status_code == 200
    tablas = resp.json()["tablas"]
    assert "gastos" in tablas
    assert "audit_log" not in tablas  # nunca expuesta
