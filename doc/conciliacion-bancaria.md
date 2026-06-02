# Conciliación bancaria — Guía del proceso

Documenta cómo cargar la cartola del banco y conciliarla automáticamente contra
los libros (pagos, gastos y facturas), sin que el sistema se conecte al banco.

> **Principio:** el agente **no se conecta** al banco ni al SII. Tú (o tu sistema)
> subes la cartola como CSV; el agente la cruza contra tus registros y te muestra
> el % conciliado y las excepciones a revisar. Convierte un proceso de horas en
> "revisar las excepciones".

---

## 1. Qué hace el Agente Conciliación

Cruza cada movimiento de la cartola contra los registros de los libros:

| Lado de la cartola | Calza contra |
|--------------------|--------------|
| Abono (monto **positivo**, ingreso) | `pagos` |
| Cargo (monto **negativo**, egreso) | `gastos` y `documentos_tributarios` |

**Regla de match:** mismo monto (tolerancia ±$1) y fecha dentro de ±3 días.
Cada registro de libro se usa una sola vez.

Reporta:
- **% conciliado** y monto conciliado.
- **Movimientos sin respaldo**: están en el banco pero no tienen registro en los
  libros (ej. comisiones, cargos no contabilizados) → son las excepciones a revisar.
- **Registros de libro sin movimiento bancario** (lo contrario).

---

## 2. Formato de la cartola (CSV)

Primera fila = nombres de columna. Columnas:

| Columna | Obligatoria | Descripción |
|---------|-------------|-------------|
| `fecha` | sí | `YYYY-MM-DD` |
| `monto` | sí | con signo: **+** abono (ingreso), **−** cargo (egreso) |
| `glosa` | no | descripción del movimiento en la cartola |
| `referencia` | no | nº de operación/documento si la cartola lo trae |

Ejemplo (`doc/ejemplos/cartola_ejemplo.csv`):

```csv
fecha,glosa,monto,referencia
2026-05-04,Abono Transbank hospedaje,336000,TBK-0504A
2026-05-04,Transferencia reserva directa,460000,TEF-0504
2026-05-05,Pago remuneraciones personal,-814000,RH-0505
2026-05-20,Comision mantencion cuenta,-9990,BANCO-COM
```

> La mayoría de los bancos chilenos permiten exportar la cartola a Excel/CSV.
> Ajusta los nombres de columna a `fecha,glosa,monto,referencia` y unifica el
> monto en una sola columna con signo (cargos en negativo).

---

## 3. Cómo subir la cartola

El endpoint de importación es genérico (`/api/ingest/{tabla}`). El campo del
archivo se llama **`archivo`**.

**Paso 1 — Validar (dry-run, no escribe nada):**
```bash
curl -X POST "https://api.majorbi.com/api/ingest/movimientos_bancarios?modo=validar" \
  -H "Authorization: Bearer <API_KEY>" \
  -F "archivo=@cartola.csv"
```
Devuelve columnas reconocidas, filas a insertar y un preview de 3 filas.

**Paso 2 — Insertar (en transacción; si falla una fila, rollback total):**
```bash
curl -X POST "https://api.majorbi.com/api/ingest/movimientos_bancarios?modo=insertar" \
  -H "Authorization: Bearer <API_KEY>" \
  -F "archivo=@cartola.csv"
```

---

## 4. Ver la conciliación

**En vivo (API):**
```bash
curl "https://api.majorbi.com/api/agents/conciliacion?dias=30" \
  -H "Authorization: Bearer <API_KEY>"
# formato=markdown para verlo legible
```

**En el dashboard semanal:** aparece la tarjeta **"Conciliación bancaria"** con
el % conciliado y la tabla de movimientos sin respaldo. Si no hay cartola
cargada en el período, muestra un aviso para subirla.

---

## 5. Ejemplo real ejecutado (prueba en producción)

Se cargó una cartola de prueba de **mayo 2026** (11 movimientos: 8 que calzan con
pagos/gastos reales + 3 excepciones a propósito).

**Carga:**
```
VALIDAR  → filas_a_insertar: 11, columnas_validas: [fecha, glosa, monto, referencia]
INSERTAR → filas_procesadas: 11
```

**Resultado de la conciliación (corte 2026-05-31, ventana 30 días):**

| Métrica | Valor |
|---------|-------|
| Movimientos | 11 |
| Conciliados | 8 (**72,7%**) |
| Monto conciliado | $2.335.000 |
| Sin respaldo | 3 |

**Movimientos sin respaldo detectados (las excepciones a revisar):**
- `2026-05-20  −$9.990   Comisión mantención cuenta`
- `2026-05-22  −$15.770  Cargo cheque protestado`
- `2026-05-25  +$24.990  Abono no identificado`

Interpretación: esos 3 movimientos están en el banco pero no en los libros →
hay que contabilizarlos (las comisiones bancarias suelen ser gasto no registrado;
el abono no identificado puede ser un pago de cliente sin asociar).

---

## 6. Relación con el F29 exacto

El Agente IVA calcula el **F29** usando como crédito las facturas con estado
`registrado` en `documentos_tributarios`. Para que el F29 sea exacto (y no la
estimación `gastos × 19%`), marca los documentos como registrados:

```bash
curl -X PATCH "https://api.majorbi.com/api/tributario/documentos/<ID>" \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"nuevo_estado": "registrado"}'
```
El reporte indica la fuente del crédito en `iva_credito_fuente`
(`documentos` | `estimado`).

---

## 7. Limpiar los datos de prueba

Los movimientos de prueba se cargaron con referencias identificables. Para
borrarlos:

```sql
DELETE FROM hotel_mbi.movimientos_bancarios
WHERE referencia IN ('TBK-0504A','TEF-0504','TBK-0505A','TBK-0505B',
                     'RH-0505','SERV-0505E','SERV-0505A','PROV-0515',
                     'BANCO-COM','BANCO-CHQ','SIN-ID');
```

---

## 8. Límites (honestos)

- Plataformas como TryLuca/Parrotfy logran ~95% automático **porque se conectan**
  al banco y al SII. Aquí, por diseño, no nos conectamos: el % depende de la
  calidad de la cartola que subas y de las reglas de match.
- El match es por monto + fecha. Movimientos agrupados (un depósito que junta
  varios pagos) o con montos netos de comisión no calzarán exactos y caerán como
  excepción para revisión manual.
