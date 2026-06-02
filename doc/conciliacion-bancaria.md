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
| Cargo (monto **negativo**, egreso) | `gastos` (libro de egresos / salida de caja) |

> Las facturas (`documentos_tributarios`) **no** se usan en la conciliación
> bancaria — alimentan el IVA/F29. Usar solo `gastos` evita contar dos veces el
> mismo egreso.

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

## 5. Ejemplo real (producción, mayo 2026)

El generador diario produce una cartola realista (espejo de pagos/gastos con
excepciones). Resultado de la conciliación de mayo (corte 2026-05-31, 30 días):

| Métrica | Valor |
|---------|-------|
| Movimientos | 146 |
| Conciliados | 131 (**89,7%**) |
| Movimientos sin respaldo | 15 |
| Registros de libro sin movimiento | 15 |

**Tipos de excepción que aparecen** (como en un banco real):
- `Abono Transbank neto comisión` — el depósito llega descontada la comisión de
  tarjeta, no calza por monto.
- `Comisión mantención cuenta`, `Comisión por transferencias`,
  `Impuesto al giro / timbres`, `PAC servicios no contabilizado`.
- `Abono no identificado`, `Reverso/devolución bancaria`.

Esas excepciones (~10%) son justo lo que un contador revisa a mano.

> Nota: el `pct_conciliado` depende de la calidad de la cartola y de las reglas
> de match. El generador apunta a ~90%; con cartolas reales reflejará tu operación.

---

## 6. El F29 (modelo completo)

El F29 **no es solo IVA débito − crédito**. El Agente IVA/F29 modela los
principales componentes:

```
  IVA débito (ventas afectas × 19%)
− IVA crédito (compras con IVA)
− Remanente de crédito del mes anterior
─────────────────────────────────────
= IVA a pagar
+ PPM  (pago provisional mensual = ingresos × tasa)
+ Retención de honorarios (boletas de terceros × 13,75%)
─────────────────────────────────────
= TOTAL F29 a pagar
```

Campos en `agente_iva.f29`: `iva_debito`, `iva_credito`, `remanente_anterior`,
`iva_a_pagar`, `remanente_siguiente`, `ppm`, `ppm_tasa_pct`,
`retencion_honorarios`, `total_a_pagar`, `vencimiento`, `dias_para_vencimiento`.

**Crédito de IVA** — fuente en `acumulado_mes.iva_credito_fuente`:

- **`documentos`**: IVA de las facturas `registrado` del mes (exacto, recomendado).
- **`estimado`** (fallback): `gastos × 19%`, **excluyendo Personal y Honorarios**
  (no llevan IVA), para no sobreestimar.

Para que el crédito sea exacto, marca las facturas como registradas:

```bash
curl -X PATCH "https://api.majorbi.com/api/agents/tributario/documentos/<ID>" \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"nuevo_estado": "registrado"}'
```

**Ejemplo real (mayo 2026):** débito $5.024.512 − crédito $151.620 − remanente $0
= IVA a pagar $4.872.892; + PPM $66.112 + retención honorarios $34.375
= **TOTAL F29 $4.973.379** (vence 2026-06-20).

> Importante: el IVA débito (ventas) suele ser bastante mayor que el crédito
> (compras) en un hotel, porque el mayor costo —las remuneraciones— no genera
> crédito de IVA. Un saldo de IVA a pagar mes a mes es lo normal.

**Parámetros / límites:** `PPM_TASA` (0,25%) y `RETENCION_HONORARIOS` (13,75%)
son constantes en `agents/tributario/_common.py`. El PPM real depende del
régimen y la tasa recalculada anual; el remanente se calcula iterando los meses
del año en curso (sin reajuste IPC/UTM). No reemplaza al contador.

---

## 7. Datos en producción

La cartola y las facturas de prueba/demo ya no se cargan a mano: las genera el
**cron diario** (`scripts/generar_datos.py`), espejo de los pagos/gastos del
período con excepciones realistas. Para limpiar la cartola generada de un rango
(si quieres partir de tu cartola real):

```sql
DELETE FROM hotel_mbi.movimientos_bancarios
WHERE fecha BETWEEN '2026-05-01' AND '2026-05-31';
```

---

## 8. Límites (honestos)

- Plataformas como TryLuca/Parrotfy logran ~95% automático **porque se conectan**
  al banco y al SII. Aquí, por diseño, no nos conectamos: el % depende de la
  calidad de la cartola que subas y de las reglas de match.
- El match es por monto + fecha. Movimientos agrupados (un depósito que junta
  varios pagos) o con montos netos de comisión no calzarán exactos y caerán como
  excepción para revisión manual.
