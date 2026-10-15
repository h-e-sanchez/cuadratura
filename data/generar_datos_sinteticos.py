"""Genera la nómina, el maestro de centros de costo y las partidas SAP de Servicios Ejemplo SpA.

Todo es sintético y reproducible (semilla fija). Las tasas de cotización e impuesto están
simplificadas: el objetivo es la cuadratura, no el cálculo legal de la liquidación.

Este generador no importa el motor: arma por su cuenta lo que la interfaz habría contabilizado y
siembra diferencias conocidas. `verdad.csv` guarda cada una, y los tests exigen que el motor las
encuentre todas, sin inventar otras:

- **Concepto sin cuenta:** un bono de antigüedad nuevo que nadie agregó al mapeo.
- **Centro de costo bloqueado:** una bodega cerrada en SAP que la nómina sigue usando.
- **Centro de costo inexistente:** un código mal digitado en la ficha de dos colaboradores.
  La interfaz deja el gasto de ambos en `CC-ADM-00` (gastos por asignar), que hay que reclasificar.
- **Documento duplicado:** el documento de aportes del empleador contabilizado dos veces.
- **Asiento manual:** una provisión de bono registrada a mano, sin origen en la nómina.
- **Dígitos traspuestos:** la gratificación de una planta digitada con dos cifras invertidas al
  corregir la interfaz; la contrapartida de remuneraciones por pagar se ajustó para que cuadre.
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MAPEO = json.loads((AQUI.parent / "config" / "mapeo.json").read_text(encoding="utf-8"))
PERIODO = "2026-11"
REF = f"NOM-{PERIODO}"
FECHA = "2026-11-30"
POR_ASIGNAR = "CC-ADM-00"

CECOS = [
    ("CC-ADM-00", "Gastos por asignar", "Administración", "N"),
    ("CC-ADM-01", "Gerencia General", "Administración", "N"),
    ("CC-ADM-02", "Finanzas", "Administración", "N"),
    ("CC-ADM-03", "Personas", "Administración", "N"),
    ("CC-OPE-01", "Planta Maipú", "Operaciones", "N"),
    ("CC-OPE-02", "Planta Pudahuel", "Operaciones", "N"),
    ("CC-OPE-03", "Logística", "Operaciones", "N"),
    ("CC-OPE-04", "Bodega Quilicura (cerrada)", "Operaciones", "S"),
    ("CC-COM-01", "Ventas Norte", "Comercial", "N"),
    ("CC-COM-02", "Ventas Sur", "Comercial", "N"),
    ("CC-COM-03", "Marketing", "Comercial", "N"),
    ("CC-TI-01", "Tecnología", "TI", "N"),
]
DOTACION = {"CC-ADM-01": 4, "CC-ADM-02": 8, "CC-ADM-03": 7, "CC-OPE-01": 28, "CC-OPE-02": 24, "CC-OPE-03": 14,
            "CC-OPE-04": 3, "CC-COM-01": 10, "CC-COM-02": 9, "CC-COM-03": 5, "CC-TI-01": 8}
SUELDOS = {"Administración": (900_000, 3_200_000), "Operaciones": (620_000, 1_300_000),
           "Comercial": (750_000, 1_900_000), "TI": (1_400_000, 3_000_000)}
CECO_MAL_DIGITADO = ("CC-COM-04", 2)  # dos fichas de Ventas Sur con el código mal escrito
TOPE_GRATIFICACION = 213_000
BONO_ANTIGUEDAD = ("BONO_ANTIGUEDAD", 75_000, 6)


def impuesto(tributable: int) -> int:
    """Tabla simplificada de impuesto único mensual."""
    if tributable <= 950_000:
        return 0
    if tributable <= 2_100_000:
        return round((tributable - 950_000) * 0.04)
    return round(46_000 + (tributable - 2_100_000) * 0.08)


def generar_nomina(rng: random.Random) -> list[dict]:
    area = {c: a for c, _, a, _ in CECOS}
    fichas = []
    n = 0
    for ceco, dotacion in DOTACION.items():
        for _ in range(dotacion):
            n += 1
            fichas.append([f"COL-{n:04d}", ceco])
    sur = [f for f in fichas if f[1] == "CC-COM-02"]
    for f in sur[:CECO_MAL_DIGITADO[1]]:
        f[1] = CECO_MAL_DIGITADO[0]
    con_antiguedad = set(rng.sample([f[0] for f in fichas], BONO_ANTIGUEDAD[2]))

    filas = []
    for colaborador, ceco in fichas:
        a = area.get(ceco, area["CC-COM-02"])
        lo, hi = SUELDOS[a]
        base = rng.randrange(lo, hi, 10_000)
        conceptos = {"SUELDO_BASE": base, "GRATIFICACION": min(round(base * 0.25), TOPE_GRATIFICACION)}
        if a in ("Operaciones", "Comercial") and rng.random() < 0.5:
            conceptos["BONO_PRODUCCION"] = rng.randrange(40_000, 260_000, 5_000)
        if a == "Operaciones" and rng.random() < 0.35:
            conceptos["HORAS_EXTRA"] = round(base / 30 / 8 * 1.5 * rng.randint(4, 24))
        if colaborador in con_antiguedad:
            conceptos[BONO_ANTIGUEDAD[0]] = BONO_ANTIGUEDAD[1]
        imponible = sum(conceptos.values())
        conceptos["COLACION"] = 60_000
        conceptos["MOVILIZACION"] = 40_000
        afp, salud, cesantia = round(imponible * 0.1144), round(imponible * 0.07), round(imponible * 0.006)
        conceptos.update({"AFP": afp, "SALUD": salud, "SEG_CESANTIA_TRAB": cesantia,
                          "IMPUESTO_UNICO": impuesto(imponible - afp - salud - cesantia),
                          "APORTE_SIS": round(imponible * 0.0149), "SEG_CESANTIA_EMP": round(imponible * 0.024),
                          "MUTUAL": round(imponible * 0.0093)})
        filas += [{"periodo": PERIODO, "colaborador": colaborador, "ceco": ceco, "concepto": k, "monto": v}
                  for k, v in conceptos.items() if v]
    return filas


def contabilizar(nomina: list[dict]) -> dict[str, dict[tuple[str, str], int]]:
    """Lo que la interfaz carga en SAP: dos documentos, gasto con centro inválido a gastos por asignar."""
    validos = {c for c, _, _, b in CECOS if b == "N"}
    docs: dict[str, dict[tuple[str, str], int]] = {"rem": defaultdict(int), "apo": defaultdict(int)}
    for f in nomina:
        regla = MAPEO["conceptos"].get(f["concepto"])
        if not regla:
            continue
        ceco = f["ceco"] if f["ceco"] in validos else POR_ASIGNAR
        if regla["tipo"] == "haber":
            docs["rem"][(regla["cuenta"], ceco)] += f["monto"]
            docs["rem"][(MAPEO["cuenta_liquido"], "")] -= f["monto"]
        elif regla["tipo"] == "descuento":
            docs["rem"][(regla["cuenta"], "")] -= f["monto"]
            docs["rem"][(MAPEO["cuenta_liquido"], "")] += f["monto"]
        else:
            docs["apo"][(regla["cuenta"], ceco)] += f["monto"]
            docs["apo"][(regla["contrapartida"], "")] -= f["monto"]
    return docs


def trasponer(n: int) -> int:
    """Invierte las dos primeras cifras distintas contiguas desde la izquierda (4.315.200 -> 4.135.200)."""
    s = list(str(n))
    for i in range(1, len(s) - 1):
        if s[i] != s[i + 1]:
            s[i], s[i + 1] = s[i + 1], s[i]
            return int("".join(s))
    raise ValueError(n)


def partidas(doc: str, ref: str, lineas: dict[tuple[str, str], int], texto: str) -> list[dict]:
    return [{"documento": doc, "fecha": FECHA, "referencia": ref, "cuenta": c, "ceco": k, "debe": max(v, 0), "haber": max(-v, 0),
             "texto": texto} for (c, k), v in sorted(lineas.items()) if v]


def esperado(nomina: list[dict]) -> dict[tuple[str, str], int]:
    """Asiento esperado según la nómina, con el centro de costo que trae cada ficha."""
    neto: dict[tuple[str, str], int] = defaultdict(int)
    for f in nomina:
        regla = MAPEO["conceptos"].get(f["concepto"])
        if not regla:
            continue
        if regla["tipo"] == "haber":
            neto[(regla["cuenta"], f["ceco"])] += f["monto"]
            neto[(MAPEO["cuenta_liquido"], "")] -= f["monto"]
        elif regla["tipo"] == "descuento":
            neto[(regla["cuenta"], "")] -= f["monto"]
            neto[(MAPEO["cuenta_liquido"], "")] += f["monto"]
        else:
            neto[(regla["cuenta"], f["ceco"])] += f["monto"]
            neto[(regla["contrapartida"], "")] -= f["monto"]
    return neto


def main() -> None:
    rng = random.Random(2026)
    nomina = generar_nomina(rng)
    docs = contabilizar(nomina)
    verdad = []

    # dígitos traspuestos en la gratificación de Planta Pudahuel; remuneraciones por pagar absorbe la diferencia
    clave = ("610102", "CC-OPE-02")
    original = docs["rem"][clave]
    errado = trasponer(original)
    delta = errado - original
    docs["rem"][clave] = errado
    docs["rem"][(MAPEO["cuenta_liquido"], "")] -= delta
    verdad += [{"seccion": "cuadratura", "clave": "610102", "detalle": "CC-OPE-02", "tipo": "Diferencia de monto", "monto": delta},
               {"seccion": "cuadratura", "clave": MAPEO["cuenta_liquido"], "detalle": "", "tipo": "Diferencia de monto",
                "monto": -delta}]

    sap = (partidas("1900004811", REF, docs["rem"], f"Remuneraciones {PERIODO}")
           + partidas("1900004812", REF, docs["apo"], f"Aportes empleador {PERIODO}")
           + partidas("1900004813", REF, docs["apo"], f"Aportes empleador {PERIODO}"))
    manual = {("610103", "CC-COM-01"): 850_000, (MAPEO["cuenta_liquido"], ""): -850_000}
    sap += partidas("1900004820", "PROV-BONO-11", manual, "Provisión bono comercial noviembre")
    verdad += [{"seccion": "observado", "clave": "1900004813", "detalle": "1900004812", "tipo": "Documento duplicado",
                "monto": sum(v for (c, _), v in docs["apo"].items() if c.startswith("6"))},
               {"seccion": "observado", "clave": "1900004820", "detalle": "PROV-BONO-11",
                "tipo": "Asiento manual sin origen en la nómina", "monto": 850_000}]

    # rechazos de la validación
    def rechazo(tipo: str, valor: str, filtro) -> dict:
        lineas = [f for f in nomina if filtro(f)]
        return {"seccion": "rechazo", "clave": valor, "detalle": len(lineas), "tipo": tipo, "monto": sum(f["monto"] for f in lineas)}
    verdad += [rechazo("Centro de costo bloqueado en SAP", "CC-OPE-04", lambda f: f["ceco"] == "CC-OPE-04"),
               rechazo("Centro de costo inexistente en SAP", CECO_MAL_DIGITADO[0], lambda f: f["ceco"] == CECO_MAL_DIGITADO[0]),
               rechazo("Concepto sin cuenta contable", BONO_ANTIGUEDAD[0], lambda f: f["concepto"] == BONO_ANTIGUEDAD[0])]

    # reclasificaciones: el gasto de los centros inválidos quedó en gastos por asignar
    esp = esperado(nomina)
    for cuenta in sorted({c for c, k in esp if c.startswith("6")}):
        faltas = {k: v for (c, k), v in esp.items() if c == cuenta and k in ("CC-OPE-04", CECO_MAL_DIGITADO[0]) and v}
        for k, v in sorted(faltas.items()):
            verdad.append({"seccion": "cuadratura", "clave": cuenta, "detalle": k, "tipo": "Reclasificar centro de costo", "monto": -v})
        if faltas:
            verdad.append({"seccion": "cuadratura", "clave": cuenta, "detalle": POR_ASIGNAR, "tipo": "Reclasificar centro de costo",
                           "monto": sum(faltas.values())})

    escribir("nomina.csv", nomina)
    escribir("maestro_cecos.csv", [{"ceco": c, "descripcion": d, "area": a, "bloqueado": b} for c, d, a, b in CECOS])
    escribir("sap_partidas.csv", sap)
    escribir("verdad.csv", verdad)
    print(f"{len({f['colaborador'] for f in nomina})} colaboradores, {len(nomina)} líneas de nómina, "
          f"{len(sap)} partidas SAP, {len(verdad)} filas de verdad")


def escribir(nombre: str, filas: list[dict]) -> None:
    with open(AQUI / nombre, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(filas)


if __name__ == "__main__":
    main()
