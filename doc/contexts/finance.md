# Contexto: Finance

## Reporte semanal ejecutivo (`/api/report/weekly`)

### Decisión de diseño
El reporte semanal usaba el rol `"gerente"` hardcodeado, ignorando el rol real del usuario autenticado.

**Solución acordada:** usar el rol del usuario que hace el request (ya disponible via `Depends(get_role)`), consistente con el resto de los endpoints.

**Por qué:** cada cliente puede nombrar sus roles distinto (`administrador`, `owner`, `director`). El hardcoding a `"gerente"` rompe silenciosamente en deployments sin ese rol.
