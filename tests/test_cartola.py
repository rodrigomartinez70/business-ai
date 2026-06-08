"""Tests del normalizador de cartolas bancarias (sin DB)."""
from datetime import date
from src.finanzas import cartola


def test_num_cl():
    assert cartola.num_cl("15.000") == 15000.0          # un punto, 3 dígitos → miles
    assert cartola.num_cl("1.985.000") == 1985000.0     # múltiples puntos → miles
    assert cartola.num_cl("1.234,56") == 1234.56        # punto miles, coma decimal
    assert cartola.num_cl("-2.500") == -2500.0
    assert cartola.num_cl("(3.000)") == -3000.0
    assert cartola.num_cl("") == 0.0


def test_parse_fecha():
    assert cartola.parse_fecha("03/06/2026") == date(2026, 6, 3)
    assert cartola.parse_fecha("2026-06-03") == date(2026, 6, 3)
    assert cartola.parse_fecha("basura") is None


def test_cartola_cargo_abono_con_metadata():
    csv = (
        "Banco Ejemplo - Cartola Cuenta Corriente\n"
        "Cliente: ACME SpA;Cuenta: 1234567\n"
        "Fecha;Descripción;Cargo;Abono;Saldo\n"
        "03/06/2026;COMPRA SUPERMERCADO;15.000;;1.985.000\n"
        "04/06/2026;TRANSFERENCIA RECIBIDA;;250.000;2.235.000\n"
        "05/06/2026;PAGO PROVEEDOR;1.200.500;;1.034.500\n"
        ";TOTALES;1.215.500;250.000;\n"
    ).encode("utf-8")
    r = cartola.normalizar_cartola(csv)
    m = r["movimientos"]
    assert len(m) == 3                       # fila TOTALES (sin fecha) descartada
    assert m[0]["monto"] == -15000.0         # cargo → negativo
    assert m[1]["monto"] == 250000.0         # abono → positivo
    assert m[2]["monto"] == -1200500.0
    assert m[1]["glosa"] == "TRANSFERENCIA RECIBIDA"


def test_cartola_monto_unico_coma():
    csv = (
        "Fecha,Glosa,Monto,Documento\n"
        "06-06-2026,Venta Webpay,150000,REF001\n"
        "07-06-2026,Comision banco,-2500,\n"
    ).encode("utf-8")
    r = cartola.normalizar_cartola(csv)
    m = r["movimientos"]
    assert len(m) == 2
    assert m[0]["monto"] == 150000.0 and m[0]["referencia"] == "REF001"
    assert m[1]["monto"] == -2500.0
