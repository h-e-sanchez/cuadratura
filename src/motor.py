"""Motor de cuadratura de remuneraciones: cruza el libro de remuneraciones con lo contabilizado en SAP.

El flujo replica la integración entre un software de nómina y SAP FI, en cinco pasos:

1. **Validar:** cada concepto de la nómina debe tener cuenta contable (`config/mapeo.json`) y cada
   centro de costo debe existir y estar vigente en el maestro de SAP. Lo que falla queda como
   rechazo, con su monto y los colaboradores afectados.
2. **Asiento:** agrega la nómina en dos documentos cuadrados (remuneraciones y aportes del
   empleador), por cuenta y centro de costo, y lo exporta con los campos estándar de una carga
   masiva FI (`BUKRS`, `BUDAT`, `HKONT`, `KOSTL`, `SHKZG`, `WRBTR`…).
3. **Depurar SAP:** separa los documentos contabilizados que no se deben cuadrar: asientos
   manuales sin origen en la nómina y documentos duplicados (mismas líneas que otro documento
   con la misma referencia).
4. **Cuadrar:** compara lo esperado con lo contabilizado por cuenta y centro de costo, y
   clasifica cada diferencia (reclasificar centro de costo, diferencia de monto, falta o sobra).
5. **Puente:** explica la diferencia de gasto total entre nómina y SAP partida por partida. Lo
   que no tiene explicación queda a la vista y debe ser $0.

Solo biblioteca estándar: el mismo archivo corre en los tests, en la CLI, en la API y en el
navegador (Pyodide).
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

CECO_POR_ASIGNAR = "CC-ADM-00"  # donde la interfaz deja el gasto que trae un centro de costo inválido
SOCIEDAD = "1000"
DOC_REMUNERACIONES = "Remuneraciones"
DOC_APORTES = "Aportes del empleador"
TIPOS_GASTO = ("haber", "aporte")


@dataclass
class LineaNomina:
    periodo: str
    colaborador: str
    ceco: str
    concepto: str
    monto: int


@dataclass
class Ceco:
    ceco: str
    descripcion: str
    area: str
    bloqueado: bool


@dataclass
class Partida:
    documento: str
    fecha: str
    referencia: str
    cuenta: str
    ceco: str
    debe: int
    haber: int
    texto: str = ""


@dataclass
class LineaAsiento:
    documento: str
    cuenta: str
    ceco: str
    debe: int
    haber: int
    glosa: str


# --- lectura ----------------------------------------------------------------------------------------

def _entero(texto: str) -> int:
    limpio = (texto or "").strip().replace("$", "").replace(" ", "")
    if not limpio:
        return 0
    if "," in limpio and "." in limpio:  # 1.234.567,00
        limpio = limpio.replace(".", "").replace(",", ".")
    elif limpio.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", limpio):  # 1.234.567
        limpio = limpio.replace(".", "")
    return round(float(limpio.replace(",", ".")))


def _filas(texto: str) -> list[dict]:
    muestra = texto[:2000]
    separador = ";" if muestra.count(";") > muestra.count(",") else ","
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
            for fila in csv.DictReader(io.StringIO(texto.lstrip("﻿")), delimiter=separador)]


def leer_nomina(texto: str) -> list[LineaNomina]:
    """Columnas: periodo, colaborador, ceco, concepto, monto (una fila por colaborador y concepto)."""
    return [LineaNomina(f.get("periodo", ""), f["colaborador"], f["ceco"].upper(), f["concepto"].upper(), _entero(f["monto"]))
            for f in _filas(texto)]


def leer_cecos(texto: str) -> dict[str, Ceco]:
    """Maestro de centros de costo exportado de SAP: ceco, descripcion, area, bloqueado (S/N)."""
    return {f["ceco"].upper(): Ceco(f["ceco"].upper(), f.get("descripcion", ""), f.get("area", ""),
                                    f.get("bloqueado", "N").upper() in ("S", "SI", "X", "1", "TRUE"))
            for f in _filas(texto)}


def leer_partidas(texto: str) -> list[Partida]:
    """Partidas contabilizadas en SAP: documento, fecha, referencia, cuenta, ceco, debe, haber, texto."""
    return [Partida(f["documento"], f.get("fecha", ""), f.get("referencia", ""), f["cuenta"], f.get("ceco", "").upper(),
                    _entero(f.get("debe", "")), _entero(f.get("haber", "")), f.get("texto", ""))
            for f in _filas(texto)]


def leer_mapeo(texto: str) -> dict:
    return json.loads(texto)


def referencia(nomina: list[LineaNomina]) -> str:
    periodos = sorted({li.periodo for li in nomina if li.periodo})
    return f"NOM-{periodos[-1]}" if periodos else "NOM"


def fecha_cierre(ref: str) -> str:
    """Último día del periodo de la referencia (NOM-2026-11 -> 2026-11-30): la fecha de contabilización."""
    try:
        anio, mes = (int(x) for x in ref[4:].split("-"))
    except ValueError:
        return ""
    return f"{anio}-{mes:02d}-{calendar.monthrange(anio, mes)[1]}"


# --- 1. validar -------------------------------------------------------------------------------------

def validar(nomina: list[LineaNomina], cecos: dict[str, Ceco], mapeo: dict) -> list[dict]:
    """Rechazos agrupados por causa: concepto sin cuenta, centro de costo bloqueado o inexistente."""
    grupos: dict[tuple[str, str], list[LineaNomina]] = defaultdict(list)
    for li in nomina:
        if li.concepto not in mapeo["conceptos"]:
            grupos[("Concepto sin cuenta contable", li.concepto)].append(li)
        if li.ceco not in cecos:
            grupos[("Centro de costo inexistente en SAP", li.ceco)].append(li)
        elif cecos[li.ceco].bloqueado:
            grupos[("Centro de costo bloqueado en SAP", li.ceco)].append(li)
    return [{"tipo": tipo, "valor": valor, "lineas": len(lineas), "colaboradores": len({li.colaborador for li in lineas}),
             "monto": sum(li.monto for li in lineas)}
            for (tipo, valor), lineas in sorted(grupos.items())]


def cecos_invalidos(nomina: list[LineaNomina], cecos: dict[str, Ceco]) -> set[str]:
    return {li.ceco for li in nomina if li.ceco not in cecos or cecos[li.ceco].bloqueado}


# --- 2. asiento -------------------------------------------------------------------------------------

def asiento(nomina: list[LineaNomina], mapeo: dict, cecos: dict[str, Ceco] | None = None) -> list[LineaAsiento]:
    """Asiento de la nómina en dos documentos cuadrados, por cuenta y centro de costo.

    Las cuentas de gasto llevan centro de costo; las de balance, no. Los conceptos sin cuenta
    quedan fuera (son rechazos). Si se pasa el maestro `cecos`, el gasto con centro inválido va a
    `CECO_POR_ASIGNAR`, que es lo que hace la interfaz para no detener la carga.
    """
    conceptos = mapeo["conceptos"]
    neto: dict[tuple[str, str, str], int] = defaultdict(int)  # (documento, cuenta, ceco) -> debe - haber
    glosas: dict[str, str] = {mapeo["cuenta_liquido"]: "Remuneraciones por pagar"}
    for li in nomina:
        regla = conceptos.get(li.concepto)
        if not regla:
            continue
        ceco = li.ceco
        if cecos is not None and (ceco not in cecos or cecos[ceco].bloqueado):
            ceco = CECO_POR_ASIGNAR
        glosas[regla["cuenta"]] = regla["glosa"]
        if regla["tipo"] == "haber":
            neto[(DOC_REMUNERACIONES, regla["cuenta"], ceco)] += li.monto
            neto[(DOC_REMUNERACIONES, mapeo["cuenta_liquido"], "")] -= li.monto
        elif regla["tipo"] == "descuento":
            neto[(DOC_REMUNERACIONES, regla["cuenta"], "")] -= li.monto
            neto[(DOC_REMUNERACIONES, mapeo["cuenta_liquido"], "")] += li.monto
        else:
            neto[(DOC_APORTES, regla["cuenta"], ceco)] += li.monto
            neto[(DOC_APORTES, regla["contrapartida"], "")] -= li.monto
            glosas.setdefault(regla["contrapartida"], next(
                (r["glosa"] for r in conceptos.values() if r["cuenta"] == regla["contrapartida"]), f"{regla['glosa']} por pagar"))
    return [LineaAsiento(doc, cuenta, ceco, max(v, 0), max(-v, 0), glosas.get(cuenta, ""))
            for (doc, cuenta, ceco), v in sorted(neto.items()) if v]


def interfaz_sap(lineas: list[LineaAsiento], ref: str, fecha: str, sociedad: str = SOCIEDAD) -> list[dict]:
    """Archivo de carga con los campos estándar de un documento FI; SHKZG es S (debe) o H (haber)."""
    return [{"BUKRS": sociedad, "BLDAT": fecha, "BUDAT": fecha, "BLART": "SA", "WAERS": "CLP", "XBLNR": ref,
             "BKTXT": li.documento, "HKONT": li.cuenta, "KOSTL": li.ceco, "SHKZG": "S" if li.debe else "H",
             "WRBTR": li.debe or li.haber, "SGTXT": f"{li.glosa} {ref}"[:50]} for li in lineas]


# --- 3. depurar SAP ---------------------------------------------------------------------------------

def depurar(partidas: list[Partida], ref: str) -> tuple[list[Partida], list[dict]]:
    """Separa asientos manuales y documentos duplicados de las partidas que se cuadran."""
    por_doc: dict[str, list[Partida]] = defaultdict(list)
    for p in partidas:
        por_doc[p.documento].append(p)
    vistos: dict[tuple, str] = {}
    validas, observados = [], []
    for doc in sorted(por_doc):
        lineas = por_doc[doc]
        firma = tuple(sorted(Counter((p.cuenta, p.ceco, p.debe, p.haber) for p in lineas).items()))
        tipo = None
        if any(p.referencia != ref for p in lineas):
            tipo, origen = "Asiento manual sin origen en la nómina", lineas[0].referencia
        elif firma in vistos:
            tipo, origen = "Documento duplicado", vistos[firma]
        if tipo:
            observados.append({"documento": doc, "tipo": tipo, "origen": origen, "lineas": len(lineas),
                               "monto_gasto": sum(p.debe - p.haber for p in lineas if p.cuenta.startswith("6")),
                               "texto": lineas[0].texto})
        else:
            vistos[firma] = doc
            validas.extend(lineas)
    return validas, observados


# --- 4. cuadrar -------------------------------------------------------------------------------------

def cuadrar(esperado: list[LineaAsiento], validas: list[Partida], invalidos: set[str]) -> list[dict]:
    """Diferencias por cuenta y centro de costo entre el asiento esperado y lo contabilizado."""
    esp: dict[tuple[str, str], int] = defaultdict(int)
    sap: dict[tuple[str, str], int] = defaultdict(int)
    for li in esperado:
        esp[(li.cuenta, li.ceco)] += li.debe - li.haber
    for p in validas:
        sap[(p.cuenta, p.ceco)] += p.debe - p.haber
    filas = [{"cuenta": c, "ceco": k, "esperado": esp[(c, k)], "sap": sap[(c, k)], "diferencia": sap[(c, k)] - esp[(c, k)],
              "tipo": ""} for c, k in sorted(set(esp) | set(sap)) if sap[(c, k)] != esp[(c, k)]]
    for cuenta in {f["cuenta"] for f in filas}:
        faltas = [f for f in filas if f["cuenta"] == cuenta and f["ceco"] in invalidos and f["sap"] == 0]
        sobra = next((f for f in filas if f["cuenta"] == cuenta and f["ceco"] == CECO_POR_ASIGNAR), None)
        if faltas and sobra and sobra["diferencia"] == -sum(f["diferencia"] for f in faltas):
            for f in faltas + [sobra]:
                f["tipo"] = "Reclasificar centro de costo"
    for f in filas:
        if not f["tipo"]:
            f["tipo"] = "Sobra en SAP" if f["esperado"] == 0 else "Falta en SAP" if f["sap"] == 0 else "Diferencia de monto"
    return filas


# --- 5. puente --------------------------------------------------------------------------------------

def gasto(nomina: list[LineaNomina], mapeo: dict) -> int:
    conceptos = mapeo["conceptos"]
    return sum(li.monto for li in nomina if conceptos.get(li.concepto, {}).get("tipo") in TIPOS_GASTO)


def puente(gasto_nomina: int, gasto_sap: int, observados: list[dict], filas: list[dict]) -> dict:
    """Del gasto según nómina al gasto según SAP; lo que no se explica queda en `sin_explicar`."""
    de_gasto = [f for f in filas if f["cuenta"].startswith("6")]
    pasos = [
        {"concepto": "Gasto según nómina (conceptos con cuenta)", "monto": gasto_nomina},
        {"concepto": "Documentos duplicados", "monto": sum(o["monto_gasto"] for o in observados if o["tipo"] == "Documento duplicado")},
        {"concepto": "Asientos manuales sin origen en la nómina",
         "monto": sum(o["monto_gasto"] for o in observados if o["tipo"].startswith("Asiento manual"))},
        {"concepto": "Diferencias de monto", "monto": sum(f["diferencia"] for f in de_gasto if f["tipo"] == "Diferencia de monto")},
        {"concepto": "Reclasificaciones entre centros de costo (neto)",
         "monto": sum(f["diferencia"] for f in de_gasto if f["tipo"] == "Reclasificar centro de costo")},
    ]
    explicado = sum(p["monto"] for p in pasos)
    return {"pasos": pasos, "gasto_sap": gasto_sap, "sin_explicar": gasto_sap - explicado}


# --- modelo para Power BI -----------------------------------------------------------------------------

def modelo_powerbi(nomina: list[LineaNomina], cecos: dict[str, Ceco], mapeo: dict) -> dict[str, list[dict]]:
    """Esquema estrella: un hecho por colaborador y concepto, más las dimensiones de centro y concepto."""
    conceptos = mapeo["conceptos"]
    hechos = [{"periodo": li.periodo, "colaborador": li.colaborador, "ceco": li.ceco, "concepto": li.concepto,
               "tipo": conceptos.get(li.concepto, {}).get("tipo", "sin cuenta"),
               "cuenta": conceptos.get(li.concepto, {}).get("cuenta", ""), "monto": li.monto} for li in nomina]
    dim_ceco = [{"ceco": c.ceco, "descripcion": c.descripcion, "area": c.area, "estado": "Bloqueado" if c.bloqueado else "Vigente"}
                for c in cecos.values()]
    dim_ceco += [{"ceco": k, "descripcion": "No existe en SAP", "area": "Sin centro válido", "estado": "Inexistente"}
                 for k in sorted({li.ceco for li in nomina} - set(cecos))]
    dim_concepto = [{"concepto": k, "tipo": r["tipo"], "cuenta": r["cuenta"], "glosa": r["glosa"]} for k, r in conceptos.items()]
    dim_concepto += [{"concepto": k, "tipo": "sin cuenta", "cuenta": "", "glosa": "Sin mapeo"}
                     for k in sorted({li.concepto for li in nomina} - set(conceptos))]
    return {"hechos_nomina": hechos, "dim_ceco": dim_ceco, "dim_concepto": dim_concepto}


def gasto_por_area(nomina: list[LineaNomina], cecos: dict[str, Ceco], mapeo: dict) -> list[dict]:
    conceptos = mapeo["conceptos"]
    areas: dict[str, dict] = {}
    for li in nomina:
        if conceptos.get(li.concepto, {}).get("tipo") not in TIPOS_GASTO:
            continue
        c = cecos.get(li.ceco)
        area = c.area if c and not c.bloqueado else "Sin centro válido"
        a = areas.setdefault(area, {"area": area, "gasto": 0, "colaboradores": set()})
        a["gasto"] += li.monto
        a["colaboradores"].add(li.colaborador)
    return sorted(({"area": a["area"], "gasto": a["gasto"], "colaboradores": len(a["colaboradores"])} for a in areas.values()),
                  key=lambda a: -a["gasto"])


# --- todo junto ---------------------------------------------------------------------------------------

def cuadrar_texto(nomina_txt: str, cecos_txt: str, partidas_txt: str, mapeo_txt: str) -> dict:
    """Punto de entrada de la página, la CLI y la API: recibe los textos y devuelve todo en un dict."""
    nomina, cecos, mapeo = leer_nomina(nomina_txt), leer_cecos(cecos_txt), leer_mapeo(mapeo_txt)
    partidas = leer_partidas(partidas_txt)
    ref = referencia(nomina)
    rechazos = validar(nomina, cecos, mapeo)
    esperado = asiento(nomina, mapeo)
    validas, observados = depurar(partidas, ref)
    filas = cuadrar(esperado, validas, cecos_invalidos(nomina, cecos))
    gasto_sap = sum(p.debe - p.haber for p in partidas if p.cuenta.startswith("6"))
    p = puente(gasto(nomina, mapeo), gasto_sap, observados, filas)
    docs = defaultdict(lambda: [0, 0])
    for li in esperado:
        docs[li.documento][0] += li.debe
        docs[li.documento][1] += li.haber
    return {
        "referencia": ref,
        "rechazos": rechazos,
        "asiento": [asdict(li) for li in esperado],
        "interfaz": interfaz_sap(asiento(nomina, mapeo, cecos), ref, fecha_cierre(ref)),
        "documentos": [{"documento": d, "debe": v[0], "haber": v[1]} for d, v in sorted(docs.items())],
        "observados": observados,
        "cuadratura": filas,
        "puente": p,
        "areas": gasto_por_area(nomina, cecos, mapeo),
        "totales": {
            "colaboradores": len({li.colaborador for li in nomina}),
            "lineas_nomina": len(nomina),
            "gasto_nomina": p["pasos"][0]["monto"],
            "gasto_sap": gasto_sap,
            "rechazos": len(rechazos),
            "lineas_rechazadas": sum(r["lineas"] for r in rechazos),
            "documentos_sap": len({x.documento for x in partidas}),
            "documentos_observados": len(observados),
            "filas_por_cuadrar": len(filas),
            "sin_explicar": p["sin_explicar"],
        },
    }


def a_csv(filas: list[dict]) -> str:
    if not filas:
        return ""
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=list(filas[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(filas)
    return salida.getvalue()
