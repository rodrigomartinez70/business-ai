# Contexto: Analytics

## Módulo de alertas y KPIs operativos

### Decisión de diseño
Los KPIs operativos son específicos de cada negocio (un hotel tiene ocupación/ADR/RevPAR, un restaurant tiene ticket promedio/mesas ocupadas, etc.). No se pueden generalizar.

**Solución acordada:** el operador define los KPIs en `config.yaml` con SQL directo. El módulo `alertas.py` ejecuta ese SQL determinísticamente — sin LLM.

**Por qué SQL directo y no LLM:** las alertas deben ser determinísticas. El pipeline LLM es adecuado para exploración (chat, reporte semanal), pero no para monitoreo donde se necesita consistencia.

### Estructura de KPIs en config.yaml (target)
```yaml
kpis:
  - name: "Nombre del KPI"
    sql: "SELECT ... FROM ..."   # SQL ejecutable directamente
    unidad: "%" | "moneda" | "número"
    umbral_minimo: 40            # opcional
    umbral_maximo: 1000          # opcional
```

### Estado
`alertas.py` está en desarrollo. Se puede rediseñar sin preservar compatibilidad hacia atrás.
