"""Cada paso del motor por separado, con casos chicos escritos a mano."""

from __future__ import annotations

import json
from pathlib import Path

from src import motor
from src.api import atender

RAIZ = Path(__file__).resolve().parent.parent
MAPEO = motor.leer_mapeo((RAIZ / "config/mapeo.json").read_text(encoding="utf-8"))
CECOS = motor.leer_cecos("ceco,descripcion,area,bloqueado\nCC-A,Planta,Operaciones,N\nCC-B,Bodega,Operaciones,S\n"
                         "CC-ADM-00,Por asignar,Administración,N\n")
NOMINA_TXT = ("periodo;colaborador;ceco;concepto;monto\n"
              "2026-11;C1;CC-A;SUELDO_BASE;1.000.000\n"
              "2026-11;C1;CC-A;AFP;114.400\n"
              "2026-11;C1;CC-A;APORTE_SIS;14.900\n"
              "2026-11;C2;cc-b;SUELDO_BASE;800.000\n"
              "2026-11;C2;CC-B;BONO_NUEVO;50.000\n")


def test_lectura_tolera_punto_y_coma_miles_con_punto_y_minusculas():
    nomina = motor.leer_nomina(NOMINA_TXT)
    assert [li.monto for li in nomina] == [1_000_000, 114_400, 14_900, 800_000, 50_000]
    assert nomina[3].ceco == "CC-B"
    assert motor.referencia(nomina) == "NOM-2026-11"


def test_validar_separa_concepto_sin_cuenta_y_centro_bloqueado():
    rechazos = motor.validar(motor.leer_nomina(NOMINA_TXT), CECOS, MAPEO)
    assert {(r["tipo"], r["valor"], r["lineas"], r["monto"]) for r in rechazos} == {
        ("Concepto sin cuenta contable", "BONO_NUEVO", 1, 50_000),
        ("Centro de costo bloqueado en SAP", "CC-B", 2, 850_000),
    }


def test_asiento_cuadra_y_deja_el_liquido_en_remuneraciones_por_pagar():
    lineas = motor.asiento(motor.leer_nomina(NOMINA_TXT), MAPEO)
    neto = {(li.documento, li.cuenta, li.ceco): li.debe - li.haber for li in lineas}
    assert neto[(motor.DOC_REMUNERACIONES, "610101", "CC-A")] == 1_000_000
    assert neto[(motor.DOC_REMUNERACIONES, "210601", "")] == -114_400
    assert neto[(motor.DOC_REMUNERACIONES, "210501", "")] == -(1_800_000 - 114_400)
    assert neto[(motor.DOC_APORTES, "210601", "")] == -14_900
    for doc in (motor.DOC_REMUNERACIONES, motor.DOC_APORTES):
        assert sum(v for (d, _, _), v in neto.items() if d == doc) == 0


def test_asiento_con_maestro_manda_el_centro_invalido_a_por_asignar():
    lineas = motor.asiento(motor.leer_nomina(NOMINA_TXT), MAPEO, CECOS)
    assert {li.ceco for li in lineas if li.cuenta == "610101"} == {"CC-A", motor.CECO_POR_ASIGNAR}


def test_interfaz_sap_marca_debe_y_haber():
    filas = motor.interfaz_sap(motor.asiento(motor.leer_nomina(NOMINA_TXT), MAPEO, CECOS), "NOM-2026-11", "2026-11-30")
    assert sum(f["WRBTR"] for f in filas if f["SHKZG"] == "S") == sum(f["WRBTR"] for f in filas if f["SHKZG"] == "H")
    assert all(f["KOSTL"] == "" for f in filas if not f["HKONT"].startswith("6"))
    assert all(len(f["SGTXT"]) <= 50 for f in filas)


def test_depurar_detecta_duplicado_y_asiento_manual():
    partidas = motor.leer_partidas(
        "documento,fecha,referencia,cuenta,ceco,debe,haber\n"
        "1,2026-11-30,NOM-2026-11,610201,CC-A,100,0\n1,2026-11-30,NOM-2026-11,210601,,0,100\n"
        "2,2026-11-30,NOM-2026-11,610201,CC-A,100,0\n2,2026-11-30,NOM-2026-11,210601,,0,100\n"
        "3,2026-11-30,AJUSTE,610103,CC-A,50,0\n3,2026-11-30,AJUSTE,210501,,0,50\n")
    validas, observados = motor.depurar(partidas, "NOM-2026-11")
    assert {p.documento for p in validas} == {"1"}
    assert {(o["documento"], o["tipo"], o["monto_gasto"]) for o in observados} == {
        ("2", "Documento duplicado", 100), ("3", "Asiento manual sin origen en la nómina", 50)}


def test_cuadrar_clasifica_reclasificacion_y_diferencia():
    esperado = [motor.LineaAsiento("R", "610101", "CC-B", 800, 0, ""), motor.LineaAsiento("R", "610102", "CC-A", 500, 0, "")]
    sap = [motor.Partida("1", "", "", "610101", motor.CECO_POR_ASIGNAR, 800, 0),
           motor.Partida("1", "", "", "610102", "CC-A", 50, 0)]
    filas = motor.cuadrar(esperado, sap, {"CC-B"})
    assert {(f["cuenta"], f["ceco"], f["tipo"], f["diferencia"]) for f in filas} == {
        ("610101", "CC-B", "Reclasificar centro de costo", -800),
        ("610101", motor.CECO_POR_ASIGNAR, "Reclasificar centro de costo", 800),
        ("610102", "CC-A", "Diferencia de monto", -450),
    }


def test_cuadrar_sin_reclasificacion_posible_deja_falta_y_sobra():
    esperado = [motor.LineaAsiento("R", "610101", "CC-A", 800, 0, "")]
    sap = [motor.Partida("1", "", "", "610105", "CC-A", 300, 0)]
    filas = motor.cuadrar(esperado, sap, set())
    assert {(f["cuenta"], f["tipo"]) for f in filas} == {("610101", "Falta en SAP"), ("610105", "Sobra en SAP")}


def test_puente_deja_a_la_vista_lo_que_no_se_explica():
    filas = [{"cuenta": "610101", "ceco": "CC-A", "diferencia": -800, "tipo": "Falta en SAP"}]
    p = motor.puente(1_000, 200, [], filas)
    assert p["sin_explicar"] == -800


def test_api_responde_lo_mismo_que_el_motor():
    textos = {k: (RAIZ / v).read_text(encoding="utf-8") for k, v in
              {"nomina": "data/nomina.csv", "cecos": "data/maestro_cecos.csv", "sap": "data/sap_partidas.csv"}.items()}
    estado, cuerpo = atender("POST", "/cuadratura", json.dumps(textos).encode())
    assert estado == 200
    assert cuerpo == motor.cuadrar_texto(textos["nomina"], textos["cecos"], textos["sap"],
                                         (RAIZ / "config/mapeo.json").read_text(encoding="utf-8"))
    estado, cuerpo = atender("POST", "/asiento", json.dumps({**textos, "fecha": "2026-11-30"}).encode())
    assert estado == 200 and cuerpo["lineas"] and cuerpo["referencia"] == "NOM-2026-11"


def test_api_errores_claros():
    assert atender("GET", "/salud") == (200, {"ok": True})
    assert atender("POST", "/cuadratura", b"{}")[0] == 400
    assert atender("POST", "/cuadratura", b"no es json")[0] == 400
    assert atender("DELETE", "/cuadratura")[0] == 404
