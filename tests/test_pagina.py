"""La página carga el mismo motor que los tests y las cifras que citan la página y el README siguen siendo ciertas."""

from __future__ import annotations

import re
from pathlib import Path

from src import motor

RAIZ = Path(__file__).resolve().parent.parent


def _resultado() -> dict:
    return motor.cuadrar_texto(*((RAIZ / r).read_text(encoding="utf-8") for r in
                                 ("data/nomina.csv", "data/maestro_cecos.csv", "data/sap_partidas.csv", "config/mapeo.json")))


def test_la_pagina_usa_src_motor_el_mapeo_y_los_datos_de_ejemplo():
    app = (RAIZ / "app.js").read_text(encoding="utf-8")
    assert 'texto("src/motor.py")' in app
    assert 'texto("config/mapeo.json")' in app
    for ruta in re.search(r"EJEMPLO = \[(.*?)\]", app).group(1).replace('"', "").split(", "):
        assert (RAIZ / ruta).exists(), ruta
    html = (RAIZ / "index.html").read_text(encoding="utf-8")
    for id_ in re.findall(r'\$\("([\w-]+)"\)', app) + re.findall(r'"(archivo-[\w]+)"', app):
        assert f'id="{id_}"' in html, f"app.js usa #{id_}, que no está en index.html"


def test_cifras_citadas_coinciden_con_el_motor():
    t = _resultado()["totales"]
    for archivo in ("README.md", "index.html"):
        texto = (RAIZ / archivo).read_text(encoding="utf-8")
        assert f"{t['rechazos']} rechazos" in texto, archivo
        assert f"{t['documentos_observados']} documentos observados" in texto, archivo
        assert f"{t['filas_por_cuadrar']} filas por cuadrar" in texto, archivo
        assert f"{t['colaboradores']} colaboradores" in texto, archivo
        assert t["sin_explicar"] == 0 and "$0 sin explicar" in texto, archivo


def test_la_interfaz_de_la_pagina_cuadra():
    filas = _resultado()["interfaz"]
    assert {f["XBLNR"] for f in filas} == {"NOM-2026-11"}
    assert {f["BUDAT"] for f in filas} == {"2026-11-30"}
    assert sum(f["WRBTR"] for f in filas if f["SHKZG"] == "S") == sum(f["WRBTR"] for f in filas if f["SHKZG"] == "H")
