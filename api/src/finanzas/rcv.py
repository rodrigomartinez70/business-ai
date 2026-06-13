"""
Normalizador del RCV (Registro de Compras y Ventas) del SII — Chile.

Toma el CSV que se descarga del portal del SII (Detalle Registro de Compras o de
Ventas) y lo normaliza a documentos para `documentos_tributarios`. Auto-detecta si
es compras o ventas, mapea columnas por palabra clave y parsea números/fechas
chilenos (reusa los helpers del normalizador de cartola).

Es la Fase A del SII: sin certificado digital, el contador sube el CSV y el
Copiloto Tributario pasa de IVA estimado a IVA real (crédito = compras, débito =
ventas). Ver doc/design-packs.md / la conversación de diseño SII-RCV.
"""

from __future__ import annotations

import csv
import io
import logging

from .cartola import _norm, num_cl, parse_fecha, _sniff_delimiter

logger = logging.getLogger(__name__)

# Código de tipo de DTE (SII) → `tipo` en documentos_tributarios. El motor IVA
# trata 'nota_credito' con signo negativo, por eso el mapeo del 61 es importante.
_TIPO_DTE = {
    33: "factura", 34: "factura", 46: "factura",
    39: "boleta",  41: "boleta",
    52: "guia",    56: "nota_debito", 61: "nota_credito",
}

# Palabras clave por columna (match por substring, en minúsculas y sin tildes).
_KEYS = {
    "tipo_doc": ["tipo doc", "tipo dte", "tipo de documento", "tipo documento"],
    "rut":      ["rut proveedor", "rut cliente", "rut"],
    "razon":    ["razon social", "proveedor", "cliente"],
    "folio":    ["folio", "nro documento", "numero documento", "nro doc"],
    "fecha":    ["fecha docto", "fecha doc", "fecha emision", "fecha"],
    "neto":     ["monto neto", "neto"],
    "iva":      ["monto iva recuperable", "iva recuperable", "monto iva", "iva"],
    "total":    ["monto total", "total"],
}


def _detectar_clase(hs: list[str]) -> str | None:
    """compra | venta a partir de los encabezados (RUT proveedor vs RUT cliente)."""
    j = " | ".join(hs)
    if "rut proveedor" in j or "tipo compra" in j:
        return "compra"
    if "rut cliente" in j or "tipo venta" in j:
        return "venta"
    return None


def _mapear(headers: list[str]) -> tuple[dict, list[str]]:
    hs = [_norm(h) for h in headers]
    mapa: dict[str, int] = {}
    for tipo, claves in _KEYS.items():
        for i, h in enumerate(hs):
            if any(k in h for k in claves) and i not in mapa.values():
                mapa[tipo] = i
                break
    return mapa, hs


def _detectar_header(lineas: list[list[str]]) -> int:
    """Fila de encabezados: la que tiene 'folio' + algún monto (neto/iva/total)."""
    for idx, fila in enumerate(lineas[:20]):
        j = " ".join(_norm(c) for c in fila)
        if "folio" in j and ("monto neto" in j or "monto total" in j or "monto iva" in j):
            return idx
    return -1


def normalizar_rcv(contenido: bytes) -> dict:
    """Bytes de un RCV CSV → {documentos:[{clase,tipo,numero_documento,rut_contraparte,
    proveedor,fecha,monto_neto,monto_iva,monto_total}], meta:{...}}."""
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
    lineas = [f for f in csv.reader(io.StringIO(texto), delimiter=delim)
              if any((c or "").strip() for c in f)]
    if not lineas:
        raise ValueError("Archivo vacío.")

    h_idx = _detectar_header(lineas)
    if h_idx < 0:
        raise ValueError("No se encontró el encabezado del RCV "
                         "(se esperan columnas Folio + Monto Neto/IVA/Total).")
    headers = lineas[h_idx]
    mapa, hs = _mapear(headers)
    clase = _detectar_clase(hs)
    if clase is None:
        raise ValueError("No se pudo determinar si es Registro de Compras o de Ventas "
                         "(falta la columna RUT Proveedor / RUT Cliente).")
    if "folio" not in mapa or not ({"neto", "iva", "total"} & set(mapa)):
        raise ValueError(f"No se pudieron mapear las columnas mínimas. Detectadas: {list(mapa)}")

    def celda(fila, t):
        i = mapa.get(t)
        return fila[i] if i is not None and i < len(fila) else None

    def tipo_de(fila):
        raw = (celda(fila, "tipo_doc") or "").strip()
        cod = "".join(ch for ch in raw if ch.isdigit())
        return _TIPO_DTE.get(int(cod), "factura") if cod else "factura"

    docs, descartadas = [], 0
    for fila in lineas[h_idx + 1:]:
        folio = (celda(fila, "folio") or "").strip()
        f = parse_fecha(celda(fila, "fecha"))
        if not folio or not f:
            descartadas += 1                # filas de totales/subtotales sin folio o fecha
            continue
        neto  = round(num_cl(celda(fila, "neto")), 2)
        iva   = round(num_cl(celda(fila, "iva")), 2)
        total = round(num_cl(celda(fila, "total")), 2)
        if neto == 0 and iva == 0 and total == 0:
            descartadas += 1
            continue
        docs.append({
            "clase": clase,
            "tipo": tipo_de(fila),
            "numero_documento": folio[:50],
            "rut_contraparte": ((celda(fila, "rut") or "").strip()[:20] or None),
            "proveedor": ((celda(fila, "razon") or "").strip()[:100] or "—"),
            "fecha": f,
            "monto_neto": neto,
            "monto_iva": iva,
            "monto_total": total,
        })

    return {
        "documentos": docs,
        "meta": {
            "clase": clase,
            "delimitador": delim,
            "columnas_detectadas": {k: headers[i] for k, i in mapa.items() if i < len(headers)},
            "filas_descartadas": descartadas,
            "total": len(docs),
            "total_neto": round(sum(d["monto_neto"] for d in docs), 2),
            "total_iva": round(sum(d["monto_iva"] for d in docs), 2),
        },
    }
