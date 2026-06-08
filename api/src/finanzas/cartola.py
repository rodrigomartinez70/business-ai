"""
Normalizador de cartolas bancarias (Chile).

Toma la exportación CSV de cualquier banco y la normaliza a movimientos
{fecha, glosa, monto, referencia} para insertar en `movimientos_bancarios`
(monto: + abono/ingreso, − cargo/egreso), que es lo que consume la conciliación.

Robusto a las variantes habituales de los bancos chilenos:
- columnas detectadas por palabra clave (no posición fija);
- formatos cargo/abono separados o un único monto con signo;
- números chilenos (1.234.567 / 1.234,56) y fechas dd/mm/aaaa, dd-mm-aaaa, etc.;
- filas de metadata/título antes de la tabla y filas de totales se descartan.
"""

import csv
import io
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Palabras clave por tipo de columna (match por substring, en minúsculas y sin tildes).
_KEYS = {
    "fecha": ["fecha", "date", "f. mov", "f.mov", "dia"],
    "glosa": ["glosa", "descrip", "detalle", "movimiento", "concepto", "transacc", "observac"],
    "cargo": ["cargo", "debito", "giro", "egreso", "debe"],
    "abono": ["abono", "credito", "deposito", "ingreso", "haber"],
    "monto": ["monto", "importe", "valor"],
    "referencia": ["referencia", "documento", "n° doc", "nro", "operac", "comprobante", "canal"],
    "saldo": ["saldo"],
}


def _sin_tildes(s: str) -> str:
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        s = s.replace(a, b)
    return s


def _norm(s: str) -> str:
    return _sin_tildes((s or "").strip().lower())


def num_cl(s) -> float:
    """Parsea un monto en formato chileno → float (negativo si va entre paréntesis o con -)."""
    if s is None:
        return 0.0
    s = str(s).replace("$", "").replace("\xa0", "").replace(" ", "").strip()
    if not s or s in ("-", "—"):
        return 0.0
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()").lstrip("+-").strip()
    if "," in s and "." in s:               # 1.234.567,89 → thousands . / decimal ,
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                           # 1234,56 → decimal ,
        s = s.replace(",", ".")
    elif s.count(".") > 1:                    # 1.234.567 → thousands .
        s = s.replace(".", "")
    elif "." in s:                            # un solo punto: ¿miles o decimal?
        ent, dec = s.rsplit(".", 1)
        if len(dec) == 3 and ent.replace(".", "").isdigit():
            s = ent + dec                     # 1.234 → 1234 (miles, CLP sin centavos)
    try:
        val = float(s)
    except ValueError:
        return 0.0
    return -val if neg else val


def parse_fecha(s):
    s = (s or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _mapear_columnas(headers: list[str]) -> dict:
    """Asocia cada tipo de columna al índice del header que mejor matchea."""
    hs = [_norm(h) for h in headers]
    mapa: dict[str, int] = {}
    for tipo, claves in _KEYS.items():
        for i, h in enumerate(hs):
            if any(k in h for k in claves) and i not in mapa.values():
                mapa[tipo] = i
                break
    return mapa


def _detectar_header(lineas: list[list[str]]) -> int:
    """Encuentra la fila de encabezados: la primera que tenga 'fecha' + (monto|cargo|abono)."""
    for idx, fila in enumerate(lineas[:25]):
        hs = [_norm(c) for c in fila]
        tiene_fecha = any(any(k in h for k in _KEYS["fecha"]) for h in hs)
        tiene_monto = any(any(k in h for k in _KEYS["monto"] + _KEYS["cargo"] + _KEYS["abono"])
                          for h in hs)
        if tiene_fecha and tiene_monto:
            return idx
    return -1


def _sniff_delimiter(texto: str) -> str:
    muestra = "\n".join(texto.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(muestra, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if muestra.count(";") >= muestra.count(",") else ","


def normalizar_cartola(contenido: bytes) -> dict:
    """De los bytes de una cartola CSV → {movimientos:[{fecha,glosa,monto,referencia}], meta:{...}}."""
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = contenido.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("No se pudo decodificar el archivo.")

    delim = _sniff_delimiter(texto)
    lineas = list(csv.reader(io.StringIO(texto), delimiter=delim))
    lineas = [f for f in lineas if any((c or "").strip() for c in f)]  # sin filas vacías
    if not lineas:
        raise ValueError("Archivo vacío.")

    h_idx = _detectar_header(lineas)
    if h_idx < 0:
        raise ValueError("No se encontró una fila de encabezados con fecha y monto/cargo/abono.")
    headers = lineas[h_idx]
    mapa = _mapear_columnas(headers)
    if "fecha" not in mapa or not ({"monto", "cargo", "abono"} & set(mapa)):
        raise ValueError(f"No se pudieron mapear columnas. Detectadas: {list(mapa)}")

    def celda(fila, tipo):
        i = mapa.get(tipo)
        return fila[i] if i is not None and i < len(fila) else None

    movimientos, descartadas = [], 0
    for fila in lineas[h_idx + 1:]:
        f = parse_fecha(celda(fila, "fecha"))
        if not f:
            descartadas += 1            # filas de total/subtotal/saldo final sin fecha válida
            continue
        if "monto" in mapa:
            monto = num_cl(celda(fila, "monto"))
        else:
            monto = num_cl(celda(fila, "abono")) - abs(num_cl(celda(fila, "cargo")))
        if monto == 0:
            descartadas += 1
            continue
        movimientos.append({
            "fecha": f,
            "glosa": (celda(fila, "glosa") or "").strip()[:300] or None,
            "monto": round(monto, 2),
            "referencia": (celda(fila, "referencia") or "").strip()[:100] or None,
        })

    return {
        "movimientos": movimientos,
        "meta": {
            "delimitador": delim,
            "columnas_detectadas": {k: headers[i] for k, i in mapa.items() if i < len(headers)},
            "filas_descartadas": descartadas,
            "total": len(movimientos),
        },
    }
