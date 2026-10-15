/* cuadratura — corre src/motor.py en el navegador con Pyodide y pinta el resultado.
   - Carga diferida: Python se descarga recién al primer clic, sin paquetes extra (el motor
     usa solo la biblioteca estándar).
   - Los archivos del visitante se leen con FileReader y se pasan como texto al motor:
     nunca se envían a un servidor. */
(function () {
  "use strict";

  var VERSION = "0.26.4";
  var BASE = "https://cdn.jsdelivr.net/pyodide/v" + VERSION + "/full/";
  var EJEMPLO = ["data/nomina.csv", "data/maestro_cecos.csv", "data/sap_partidas.csv"];
  var ARCHIVOS = ["archivo-nomina", "archivo-cecos", "archivo-sap"];
  var cargando = null;
  var mapeo = null;
  var ultimo = null;
  var $ = function (id) { return document.getElementById(id); };

  function cargarScript(src) {
    return new Promise(function (ok, falla) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = ok;
      s.onerror = function () { falla(new Error("No se pudo descargar Python. Revisa tu conexión.")); };
      document.head.appendChild(s);
    });
  }

  function texto(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("No se pudo leer " + url);
      return r.text();
    });
  }

  function python(avisar) {
    if (!cargando) {
      cargando = (async function () {
        avisar("Descargando Python (solo la primera vez)…");
        await cargarScript(BASE + "pyodide.js");
        var py = await window.loadPyodide({ indexURL: BASE });
        py.FS.writeFile(py.FS.cwd() + "/motor.py", await texto("src/motor.py"));
        mapeo = await texto("config/mapeo.json");
        return py;
      })();
      cargando.catch(function () { cargando = null; });
    }
    return cargando;
  }

  async function cuadrar(textos) {
    var avisar = function (t) { $("estado").textContent = t; };
    $("btn-ejemplo").disabled = true;
    $("btn-propios").disabled = true;
    if (window.analitica) window.analitica.unaVez("cuadratura-ejecutada");
    try {
      var py = await python(avisar);
      avisar("Cuadrando…");
      py.globals.set("nomina_txt", textos[0]);
      py.globals.set("cecos_txt", textos[1]);
      py.globals.set("sap_txt", textos[2]);
      py.globals.set("mapeo_txt", mapeo);
      var json = await py.runPythonAsync("import json, motor\njson.dumps(motor.cuadrar_texto(nomina_txt, cecos_txt, sap_txt, mapeo_txt))");
      ultimo = JSON.parse(json);
      pintar(ultimo);
      avisar("Listo.");
    } catch (e) {
      avisar("No se pudo cuadrar: " + String(e && e.message ? e.message : e).split("\n").filter(Boolean).pop());
    } finally {
      $("btn-ejemplo").disabled = false;
      habilitarPropios();
    }
  }

  var pesos = function (n) { return (n < 0 ? "−$" : "$") + Math.abs(n).toLocaleString("es-CL"); };
  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function kpi(valor, rotulo, clase) {
    return '<div class="kpi ' + (clase || "") + '"><span class="valor">' + esc(valor) + '</span><span class="rotulo">' + esc(rotulo) + "</span></div>";
  }
  function tabla(id, cabeza, filas) {
    $(id).innerHTML = "<thead><tr>" + cabeza.map(function (c) {
      return "<th" + (c.num ? ' class="num"' : "") + ">" + esc(c.t) + "</th>";
    }).join("") + "</tr></thead><tbody>" + filas.join("") + "</tbody>";
  }
  var td = function (v, num) { return "<td" + (num ? ' class="num"' : "") + ">" + v + "</td>"; };
  var clase = function (tipo) { return tipo.indexOf("Reclasificar") === 0 ? "reclasificar" : tipo === "Diferencia de monto" ? "monto" : "otra"; };

  function pintar(r) {
    var t = r.totales;
    $("resultados").hidden = false;
    $("referencia").textContent = r.referencia;
    $("kpis").innerHTML =
      kpi(t.colaboradores, "colaboradores en la nómina") +
      kpi(pesos(t.gasto_nomina), "gasto según nómina") +
      kpi(pesos(t.gasto_sap), "gasto según SAP", t.gasto_sap === t.gasto_nomina ? "ok" : "alerta") +
      kpi(t.rechazos + " (" + t.lineas_rechazadas + " líneas)", "rechazos de la validación", t.rechazos ? "alerta" : "ok") +
      kpi(t.documentos_observados + " de " + t.documentos_sap, "documentos SAP observados", t.documentos_observados ? "alerta" : "ok") +
      kpi(pesos(t.sin_explicar), "diferencia sin explicar", t.sin_explicar ? "alerta" : "ok");

    var p = r.puente;
    $("tabla-puente").innerHTML = "<tbody>" + p.pasos.map(function (x, i) {
      return "<tr" + (i === 0 ? ' class="total"' : "") + "><td>" + (i ? "+ " : "") + esc(x.concepto) + '</td><td class="num">' + pesos(x.monto) + "</td></tr>";
    }).join("") + '<tr class="total"><td>Gasto según SAP</td><td class="num">' + pesos(p.gasto_sap) + "</td></tr>" +
      '<tr class="' + (p.sin_explicar ? "descuadra" : "cuadra") + '"><td>Sin explicar</td><td class="num">' + pesos(p.sin_explicar) + "</td></tr></tbody>";

    var max = Math.max.apply(null, r.areas.map(function (a) { return a.gasto; }).concat([1]));
    $("barras-areas").innerHTML = r.areas.map(function (a) {
      return '<div class="barra' + (a.area === "Sin centro válido" ? " invalida" : "") + '"><span>' + esc(a.area) + " · " + a.colaboradores +
        '</span><span class="pista"><span style="width:' + (100 * a.gasto / max).toFixed(1) + '%"></span></span><span class="n">' + pesos(a.gasto) + "</span></div>";
    }).join("");

    tabla("tabla-rechazos", [{ t: "Causa" }, { t: "Valor" }, { t: "Líneas", num: 1 }, { t: "Colaboradores", num: 1 }, { t: "Monto", num: 1 }],
      r.rechazos.map(function (x) {
        return "<tr>" + td(esc(x.tipo)) + td("<code>" + esc(x.valor) + "</code>") + td(x.lineas, 1) + td(x.colaboradores, 1) + td(pesos(x.monto), 1) + "</tr>";
      }));
    tabla("tabla-observados", [{ t: "Documento" }, { t: "Tipo" }, { t: "Origen" }, { t: "Texto" }, { t: "Líneas", num: 1 }, { t: "Gasto", num: 1 }],
      r.observados.map(function (o) {
        return "<tr>" + td("<code>" + esc(o.documento) + "</code>") + td(esc(o.tipo)) + td(esc(o.origen)) + td(esc(o.texto)) + td(o.lineas, 1) + td(pesos(o.monto_gasto), 1) + "</tr>";
      }));

    var tipos = [];
    r.cuadratura.forEach(function (f) { if (tipos.indexOf(f.tipo) < 0) tipos.push(f.tipo); });
    $("filtros").innerHTML = ['<button type="button" class="chip" aria-pressed="true" data-tipo="">Todas (' + r.cuadratura.length + ")</button>"]
      .concat(tipos.map(function (k) {
        var n = r.cuadratura.filter(function (f) { return f.tipo === k; }).length;
        return '<button type="button" class="chip" aria-pressed="false" data-tipo="' + esc(k) + '">' + esc(k) + " (" + n + ")</button>";
      })).join("");
    diferencias("");
    $("resultados").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function diferencias(tipo) {
    tabla("tabla-cuadratura", [{ t: "Tipo" }, { t: "Cuenta" }, { t: "Centro de costo" }, { t: "Esperado", num: 1 }, { t: "SAP", num: 1 }, { t: "Diferencia", num: 1 }],
      ultimo.cuadratura.filter(function (f) { return !tipo || f.tipo === tipo; }).map(function (f) {
        return "<tr>" + td('<span class="etiqueta-tipo ' + clase(f.tipo) + '">' + esc(f.tipo) + "</span>") + td("<code>" + esc(f.cuenta) + "</code>") +
          td(f.ceco ? "<code>" + esc(f.ceco) + "</code>" : "—") + td(pesos(f.esperado), 1) + td(pesos(f.sap), 1) + td(pesos(f.diferencia), 1) + "</tr>";
      }));
  }

  function csv(filas) {
    if (!filas.length) return "";
    var cols = Object.keys(filas[0]);
    var celda = function (v) { v = String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    return [cols.join(",")].concat(filas.map(function (f) { return cols.map(function (c) { return celda(f[c]); }).join(","); })).join("\n") + "\n";
  }
  function descargar(nombre, contenido) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([contenido], { type: "text/csv;charset=utf-8" }));
    a.download = nombre;
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }
  function leer(input) {
    return new Promise(function (ok, falla) {
      var fr = new FileReader();
      fr.onload = function () { ok(fr.result); };
      fr.onerror = function () { falla(new Error("No se pudo leer " + input.files[0].name)); };
      fr.readAsText(input.files[0], "utf-8");
    });
  }
  function habilitarPropios() {
    $("btn-propios").disabled = !ARCHIVOS.every(function (id) { return $(id).files.length; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("btn-ejemplo").addEventListener("click", async function () {
      try {
        cuadrar(await Promise.all(EJEMPLO.map(texto)));
      } catch (e) { $("estado").textContent = e.message; }
    });
    ARCHIVOS.forEach(function (id) { $(id).addEventListener("change", habilitarPropios); });
    $("btn-propios").addEventListener("click", async function () {
      try {
        cuadrar(await Promise.all(ARCHIVOS.map(function (id) { return leer($(id)); })));
      } catch (e) { $("estado").textContent = e.message; }
    });
    $("filtros").addEventListener("click", function (ev) {
      var b = ev.target.closest(".chip");
      if (!b) return;
      Array.prototype.forEach.call(this.children, function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      diferencias(b.dataset.tipo);
    });
    $("dl-cuadratura").addEventListener("click", function () { descargar("cuadratura.csv", csv(ultimo.cuadratura)); });
    $("dl-interfaz").addEventListener("click", function () { descargar("interfaz_sap.csv", csv(ultimo.interfaz)); });
    $("dl-rechazos").addEventListener("click", function () { descargar("rechazos.csv", csv(ultimo.rechazos)); });
  });
})();
