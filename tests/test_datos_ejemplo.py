"""El motor encuentra cada diferencia sembrada en los datos de ejemplo, y ninguna de más."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src import motor

RAIZ = Path(__file__).resolve().parent.parent


def _texto(ruta: str) -> str:
    return (RAIZ / ruta).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def resultado() -> dict:
    return motor.cuadrar_texto(_texto("data/nomina.csv"), _texto("data/maestro_cecos.csv"),
                               _texto("data/sap_partidas.csv"), _texto("config/mapeo.json"))


@pytest.fixture(scope="module")
def verdad() -> list[dict]:
    with open(RAIZ / "data/verdad.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _seccion(verdad: list[dict], nombre: str) -> list[dict]:
    return [v for v in verdad if v["seccion"] == nombre]


def test_rechazos_coinciden_con_la_verdad(resultado, verdad):
    esperados = {(v["tipo"], v["clave"], int(v["detalle"]), int(v["monto"])) for v in _seccion(verdad, "rechazo")}
    hallados = {(r["tipo"], r["valor"], r["lineas"], r["monto"]) for r in resultado["rechazos"]}
    assert hallados == esperados


def test_documentos_observados_coinciden_con_la_verdad(resultado, verdad):
    esperados = {(v["clave"], v["tipo"], v["detalle"], int(v["monto"])) for v in _seccion(verdad, "observado")}
    hallados = {(o["documento"], o["tipo"], o["origen"], o["monto_gasto"]) for o in resultado["observados"]}
    assert hallados == esperados


def test_cada_fila_por_cuadrar_esta_sembrada_y_bien_clasificada(resultado, verdad):
    esperados = {(v["clave"], v["detalle"], v["tipo"], int(v["monto"])) for v in _seccion(verdad, "cuadratura")}
    hallados = {(f["cuenta"], f["ceco"], f["tipo"], f["diferencia"]) for f in resultado["cuadratura"]}
    assert hallados == esperados


def test_el_puente_cierra_en_cero(resultado):
    p = resultado["puente"]
    assert p["sin_explicar"] == 0
    assert sum(x["monto"] for x in p["pasos"]) == p["gasto_sap"]


def test_el_asiento_esperado_cuadra_por_documento(resultado):
    assert len(resultado["documentos"]) == 2
    for d in resultado["documentos"]:
        assert d["debe"] == d["haber"] > 0


def test_ningun_tipo_queda_sin_clasificar(resultado):
    assert {f["tipo"] for f in resultado["cuadratura"]} <= {"Reclasificar centro de costo", "Diferencia de monto"}
