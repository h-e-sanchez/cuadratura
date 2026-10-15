"""CLI: cuadra la nómina contra SAP y deja los resultados en salida/.

    python -m src.main
    python -m src.main --nomina libro.csv --cecos maestro.csv --sap partidas.csv --fecha 2026-11-30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import motor

RAIZ = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cuadratura de remuneraciones: nómina contra SAP.")
    p.add_argument("--nomina", default=RAIZ / "data/nomina.csv", type=Path)
    p.add_argument("--cecos", default=RAIZ / "data/maestro_cecos.csv", type=Path)
    p.add_argument("--sap", default=RAIZ / "data/sap_partidas.csv", type=Path)
    p.add_argument("--mapeo", default=RAIZ / "config/mapeo.json", type=Path)
    p.add_argument("--fecha", default=None, help="fecha de contabilización del asiento (AAAA-MM-DD)")
    p.add_argument("--salida", default=RAIZ / "salida", type=Path)
    a = p.parse_args(argv)

    textos = [Path(x).read_text(encoding="utf-8") for x in (a.nomina, a.cecos, a.sap, a.mapeo)]
    r = motor.cuadrar_texto(*textos)
    nomina, cecos, mapeo = motor.leer_nomina(textos[0]), motor.leer_cecos(textos[1]), motor.leer_mapeo(textos[3])
    fecha = a.fecha or motor.fecha_cierre(r["referencia"])

    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "powerbi").mkdir(exist_ok=True)
    escribir = {
        "rechazos.csv": r["rechazos"],
        "asiento_esperado.csv": r["asiento"],
        "interfaz_sap.csv": motor.interfaz_sap(motor.asiento(nomina, mapeo, cecos), r["referencia"], fecha),
        "documentos_observados.csv": r["observados"],
        "cuadratura.csv": r["cuadratura"],
        "puente.csv": r["puente"]["pasos"] + [{"concepto": "Gasto según SAP", "monto": r["puente"]["gasto_sap"]},
                                               {"concepto": "Sin explicar", "monto": r["puente"]["sin_explicar"]}],
    }
    escribir.update({f"powerbi/{k}.csv": v for k, v in motor.modelo_powerbi(nomina, cecos, mapeo).items()})
    escribir["powerbi/cuadratura.csv"] = r["cuadratura"]
    for nombre, filas in escribir.items():
        (a.salida / nombre).write_text(motor.a_csv(filas), encoding="utf-8")

    t = r["totales"]
    pesos = lambda n: f"${n:,}".replace(",", ".")
    print(f"{r['referencia']}: {t['colaboradores']} colaboradores, gasto nómina {pesos(t['gasto_nomina'])}, "
          f"gasto SAP {pesos(t['gasto_sap'])}")
    print(f"{t['rechazos']} rechazos ({t['lineas_rechazadas']} líneas), {t['documentos_observados']} documentos observados, "
          f"{t['filas_por_cuadrar']} filas por cuadrar, sin explicar {pesos(t['sin_explicar'])}")
    print(f"Resultados en {a.salida}")
    return 0 if t["sin_explicar"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
