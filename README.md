# cuadratura

> *Cuadratura de remuneraciones entre el software de nómina y SAP: valida la nómina contra el maestro de centros de costo, genera el asiento de carga FI y explica cada peso de diferencia entre el gasto de personal según nómina y según contabilidad, hasta $0 sin explicar.*

**Demo:** <https://h-e-sanchez.github.io/cuadratura/>

Parte del portafolio **Control de gestión, construido como software**, de Hernán Elías Sánchez:
[`centinela`](https://h-e-sanchez.github.io/centinela/) es la vitrina de reportes Power BI,
[`consulta`](https://h-e-sanchez.github.io/consulta/) es el taller de SQL en el navegador,
[`cartilla`](https://h-e-sanchez.github.io/cartilla/) es el manual de Python,
[`fiabilidad`](https://h-e-sanchez.github.io/fiabilidad/) es el modelo de mantenimiento y `cuadratura`
es la integración.

## Características de ingeniería

- **Validación antes de cargar:** cada concepto de la nómina necesita cuenta contable (`config/mapeo.json`) y cada centro de costo debe existir y estar vigente en el maestro de SAP. Lo que falla queda como rechazo, con monto, líneas y colaboradores afectados.
- **Asiento cuadrado por construcción:** dos documentos (remuneraciones y aportes del empleador), gasto con centro de costo y pasivos sin él, exportados con los campos estándar de una carga FI (`BUKRS`, `BUDAT`, `XBLNR`, `HKONT`, `KOSTL`, `SHKZG`, `WRBTR`).
- **Cuadratura que se prueba sola:** aparta documentos duplicados y asientos manuales, compara por cuenta y centro de costo, propone las reclasificaciones y cierra un puente de gasto. Si queda algo sin explicar, el test falla.
- **Medido contra la verdad, cero dependencias:** `data/verdad.csv` guarda cada diferencia sembrada y los tests exigen encontrarlas todas, sin inventar otras. El motor, `src/motor.py`, usa solo la biblioteca estándar: el mismo archivo corre en `pytest`, la CLI, la API y la página con [Pyodide](https://pyodide.org/).

## Guía de uso rápido

```bash
pip install -r requirements.txt -r requirements-dev.txt
python data/generar_datos_sinteticos.py   # nómina, maestro, partidas SAP y verdad de Servicios Ejemplo SpA
python -m src.main                         # cuadra data/ y deja los resultados en salida/ (y salida/powerbi/)
python -m src.main --nomina libro.csv --cecos maestro.csv --sap partidas.csv --fecha 2026-11-30
python -m src.api --puerto 8765            # API JSON en 127.0.0.1: POST /cuadratura y POST /asiento
python -m pytest -q
ruff check .
python -m http.server 8000                 # la página en http://localhost:8000
```

```bash
curl -s http://127.0.0.1:8765/salud
# {"ok": true}
```

| Entrada | Columnas |
|---|---|
| Libro de remuneraciones | `periodo, colaborador, ceco, concepto, monto` (una fila por colaborador y concepto) |
| Maestro de centros de costo | `ceco, descripcion, area, bloqueado` (S/N) |
| Partidas contabilizadas en SAP | `documento, fecha, referencia, cuenta, ceco, debe, haber, texto` |

Acepta coma o punto y coma y miles con punto. La referencia de la nómina (`NOM-AAAA-MM`) es la que la
interfaz pone en `XBLNR`, y es la que separa lo que viene de la nómina de los asientos manuales.

Con los datos de ejemplo (120 colaboradores, 12 centros de costo) el motor encuentra 3 rechazos,
2 documentos observados y 27 filas por cuadrar, y el puente cierra con $0 sin explicar. Salidas de la CLI:

| Archivo | Para qué |
|---|---|
| `salida/rechazos.csv` | Lo que hay que corregir en la nómina o en el mapeo antes de cargar |
| `salida/interfaz_sap.csv` | El asiento listo para la carga FI |
| `salida/cuadratura.csv` y `salida/puente.csv` | Las diferencias clasificadas y el puente de gasto |
| `salida/powerbi/` | Modelo estrella para Power BI: ver [`docs/powerbi.md`](docs/powerbi.md) |

El plan está en [`ROADMAP.md`](ROADMAP.md).

## English

A payroll-to-SAP reconciliation tool by Hernán Elías Sánchez (management control, FP&A, People
Analytics). It validates the payroll register against the SAP cost-center master, builds the balanced FI
posting and its upload file, sets aside duplicated and manual SAP documents, reconciles posted amounts by
G/L account and cost center, and explains the total difference down to zero. The engine is a single
dependency-free Python file that runs in the tests, the CLI, a small JSON API and the browser (Pyodide).
All data is synthetic.

---

Diseñamos `cuadratura` para que el cierre de remuneraciones deje de depender de encontrar diferencias a mano: cada mes, el mismo motor valida, carga y explica.
