# ROADMAP

Estado al **2026-10-15**. Este archivo se edita a mano.

## Camino A — Motor · hecho

- [x] Generador de nómina, maestro de centros de costo, partidas SAP y verdad, con semilla fija y diferencias sembradas
- [x] Validación: concepto sin cuenta, centro de costo bloqueado o inexistente
- [x] Asiento en dos documentos cuadrados y archivo de carga con campos FI estándar
- [x] Depuración de SAP: documentos duplicados y asientos manuales sin origen en la nómina
- [x] Cuadratura por cuenta y centro de costo, con reclasificaciones propuestas y puente que cierra en $0
- [x] CLI con salidas CSV y modelo estrella para Power BI
- [x] API JSON mínima en biblioteca estándar (`/cuadratura`, `/asiento`)

## Camino B — Página · hecho

- [x] Cuadratura en el navegador con Pyodide, con el mismo `src/motor.py`
- [x] Carga de CSV propios sin que salgan del equipo, filtros por tipo y descargas
- [ ] CI con `ruff` + `pytest` en GitHub Actions: `.github/` queda fuera del repo hasta que el token tenga el permiso `workflow`

## Camino C — Próximo

- [ ] Varios periodos a la vez y variación mes contra mes por centro de costo
- [ ] Reporte `.pbip` en centinela sobre `salida/powerbi/`
- [ ] Lector de extractos reales de SAP (FBL3N/FAGLL03 en Excel) y de los formatos de exportación de los softwares de nómina más usados en Chile
