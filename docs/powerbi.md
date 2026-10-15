# Modelo para Power BI

`python -m src.main` deja en `salida/powerbi/` un esquema estrella listo para importar con
**Obtener datos → Texto/CSV** (o desde la carpeta, con Power Query, para sumar periodos).

## Tablas

| Tabla | Grano | Columnas |
|---|---|---|
| `hechos_nomina` | Colaborador × concepto × periodo | `periodo, colaborador, ceco, concepto, tipo, cuenta, monto` |
| `dim_ceco` | Centro de costo | `ceco, descripcion, area, estado` (Vigente, Bloqueado o Inexistente) |
| `dim_concepto` | Concepto de nómina | `concepto, tipo, cuenta, glosa` (`tipo` = haber, descuento, aporte o sin cuenta) |
| `cuadratura` | Cuenta × centro de costo | `cuenta, ceco, esperado, sap, diferencia, tipo` |

## Relaciones

- `dim_ceco[ceco]` 1 → * `hechos_nomina[ceco]`
- `dim_concepto[concepto]` 1 → * `hechos_nomina[concepto]`
- `dim_ceco[ceco]` 1 → * `cuadratura[ceco]` (las filas de cuentas de balance tienen `ceco` vacío)

`dim_ceco` incluye los centros que la nómina usa pero SAP no tiene (estado *Inexistente*), para que
ninguna fila de hechos quede sin dimensión.

## Medidas sugeridas

```DAX
Gasto personal =
CALCULATE ( SUM ( hechos_nomina[monto] ), dim_concepto[tipo] IN { "haber", "aporte" } )

Líquido a pagar =
CALCULATE ( SUM ( hechos_nomina[monto] ), dim_concepto[tipo] = "haber" )
    - CALCULATE ( SUM ( hechos_nomina[monto] ), dim_concepto[tipo] = "descuento" )

Dotación = DISTINCTCOUNT ( hechos_nomina[colaborador] )

Costo medio por colaborador = DIVIDE ( [Gasto personal], [Dotación] )

Gasto en centros inválidos =
CALCULATE ( [Gasto personal], dim_ceco[estado] IN { "Bloqueado", "Inexistente" } )

Diferencia por cuadrar = SUM ( cuadratura[diferencia] )
```

`Gasto en centros inválidos` es la cifra que el área de personas tiene que corregir antes del cierre: es
el gasto que SAP deja en *gastos por asignar*.
