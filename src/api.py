"""API mínima en biblioteca estándar para integrar la cuadratura con otros sistemas.

    python -m src.api --puerto 8765

    POST /cuadratura   {"nomina": "<csv>", "cecos": "<csv>", "sap": "<csv>", "mapeo": "<json>"?}
                       -> el mismo resultado que la página y la CLI
    POST /asiento      {"nomina": "<csv>", "cecos": "<csv>", "fecha": "AAAA-MM-DD", "mapeo": "<json>"?}
                       -> líneas listas para la carga FI en SAP, más los rechazos de la validación
    GET  /salud        -> {"ok": true}

Si falta "mapeo", usa config/mapeo.json. Escucha solo en 127.0.0.1: es para integrar en la red
interna detrás del middleware o el orquestador que ya exista, no para exponer a internet.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src import motor

MAPEO = Path(__file__).resolve().parent.parent / "config" / "mapeo.json"
TOPE_BYTES = 20 * 1024 * 1024


def atender(metodo: str, ruta: str, cuerpo: bytes = b"") -> tuple[int, dict]:
    """Toda la lógica de la API, sin red: los tests la llaman directo."""
    if metodo == "GET" and ruta == "/salud":
        return 200, {"ok": True}
    if metodo != "POST" or ruta not in ("/cuadratura", "/asiento"):
        return 404, {"error": f"No existe {metodo} {ruta}"}
    try:
        datos = json.loads(cuerpo or b"{}")
        mapeo = datos.get("mapeo") or MAPEO.read_text(encoding="utf-8")
        if ruta == "/cuadratura":
            return 200, motor.cuadrar_texto(datos["nomina"], datos["cecos"], datos["sap"], mapeo)
        nomina, cecos, m = motor.leer_nomina(datos["nomina"]), motor.leer_cecos(datos["cecos"]), motor.leer_mapeo(mapeo)
        ref = motor.referencia(nomina)
        return 200, {"referencia": ref, "rechazos": motor.validar(nomina, cecos, m),
                     "lineas": motor.interfaz_sap(motor.asiento(nomina, m, cecos), ref, datos["fecha"])}
    except KeyError as e:
        return 400, {"error": f"Falta el campo {e}"}
    except (ValueError, json.JSONDecodeError) as e:
        return 400, {"error": str(e)}


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, estado: int, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self) -> None:
        self._responder(*atender("GET", self.path))

    def do_POST(self) -> None:
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > TOPE_BYTES:
            self._responder(413, {"error": "Archivo demasiado grande"})
            return
        self._responder(*atender("POST", self.path, self.rfile.read(largo)))


def main() -> None:
    p = argparse.ArgumentParser(description="API de cuadratura de remuneraciones")
    p.add_argument("--puerto", type=int, default=8765)
    a = p.parse_args()
    print(f"Escuchando en http://127.0.0.1:{a.puerto}")
    ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador).serve_forever()


if __name__ == "__main__":
    main()
