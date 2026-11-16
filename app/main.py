"""API y servidor web del prototipo «AgroConecta · Navegación del catálogo».

Ejecutar:  uvicorn app.main:app --port 8000
Variables: CATALOGO_N (tamaño del catálogo, por defecto 50000).
"""
from __future__ import annotations

import os
import random
import statistics
import threading
import time
import uuid
from collections import OrderedDict, deque
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .catalogo_def import FACETAS
from .datos import fila_aleatoria, hojas_desde_db, obtener_catalogo
from .motores.base import MotorCatalogo
from .motores.linea_base import MotorLineaBase
from .motores.optimizado import MotorOptimizado
from .patrones.command_navegacion import SesionNavegacion, comando_desde_json
from .patrones.modelos import Consulta
from .patrones.observer_inventario import PublicadorInventario
from .patrones.strategy_orden import ORDENES

RAIZ = Path(__file__).resolve().parent.parent
N = int(os.environ.get("CATALOGO_N", "50000"))
RUTA_DB = obtener_catalogo(N)

publicador = PublicadorInventario(RUTA_DB)
MOTORES: dict[str, MotorCatalogo] = {
    "base": MotorLineaBase(RUTA_DB),
    "optimizado": MotorOptimizado(RUTA_DB, publicador),
}
SESIONES: "OrderedDict[str, tuple[SesionNavegacion, threading.Lock]]" = OrderedDict()
MAX_SESIONES = 300
LATENCIAS = {p: deque(maxlen=500) for p in MOTORES}
_rng = random.Random(7)
_hojas = hojas_desde_db(MOTORES["base"].conexiones.get())

app = FastAPI(title="AgroConecta · Navegación del catálogo", version="3.0")


# ---------------------------------------------------------------------------
def _motor(perfil: str) -> MotorCatalogo:
    if perfil not in MOTORES:
        raise HTTPException(400, f"Perfil desconocido: {perfil}")
    return MOTORES[perfil]


def _sesion(sid: str) -> tuple[SesionNavegacion, threading.Lock]:
    if sid not in SESIONES:
        raise HTTPException(404, "Sesión no encontrada")
    SESIONES.move_to_end(sid)
    return SESIONES[sid]


def _serializar(sid: str, s: SesionNavegacion) -> dict:
    v = s.vista
    assert v is not None
    filtros = s.consulta.filtros_dict()
    nodo = s.motor.arbol.nodo(s.consulta.categoria_id)
    LATENCIAS[s.motor.perfil].append(s.ultima_operacion["tiempo_ms"])
    return {
        "sesion_id": sid,
        "perfil": s.motor.perfil,
        "consulta": {"categoria_id": s.consulta.categoria_id, "filtros": filtros, "orden": s.consulta.orden},
        "ruta": [{"id": n.id, "nombre": n.nombre} for n in nodo.ruta()],
        "arbol": s.motor.arbol.raiz.a_dict(v.conteo_hojas),
        "facetas": [
            {"nombre": f.nombre, "etiqueta": f.etiqueta,
             "valores": [{"codigo": c, "etiqueta": et, "conteo": v.conteo_facetas[f.nombre][c],
                          "seleccionado": c in filtros.get(f.nombre, ())}
                         for c, et in enumerate(f.valores)]}
            for f in FACETAS
        ],
        "ordenes": [{"nombre": o.nombre, "etiqueta": o.etiqueta} for o in ORDENES.values()],
        "productos": s.productos,
        "total": v.total,
        "hay_mas": s.hay_mas(),
        "metricas": {
            "operacion": s.ultima_operacion,
            "vista_ms": round(v.tiempo_ms, 2),
            "detalle_ms": {k: round(x, 2) for k, x in v.detalle_ms.items()},
            "consultas_sql": v.consultas_sql,
            "estrategia": v.estrategia,
        },
        "historial": {"deshacer": [c.etiqueta for c in s.deshechos],
                      "rehacer": [c.etiqueta for c in reversed(s.rehechos)]},
        "version_indice": s.motor.version,
    }


# ---------------------------------------------------------------------------
@app.get("/")
def inicio():
    return FileResponse(RAIZ / "web" / "index.html")


@app.get("/api/info")
def info():
    idx = MOTORES["optimizado"].indice  # type: ignore[attr-defined]
    return {
        "productos": idx.n_productos,
        "indice": {"memoria_mb": round(idx.memoria_mb(), 1),
                   "construccion_ms": round(idx.tiempo_construccion_ms, 1),
                   "version": idx.version},
        "eventos_publicados": publicador.eventos_publicados,
        "sesiones_activas": len(SESIONES),
    }


@app.post("/api/sesiones")
def crear_sesion(datos: dict = Body(default={})):
    perfil = datos.get("perfil", "optimizado")
    sesion = SesionNavegacion(_motor(perfil))
    sid = uuid.uuid4().hex[:12]
    SESIONES[sid] = (sesion, threading.Lock())
    while len(SESIONES) > MAX_SESIONES:
        SESIONES.popitem(last=False)
    return _serializar(sid, sesion)


@app.get("/api/sesiones/{sid}")
def ver_sesion(sid: str):
    s, _ = _sesion(sid)
    return _serializar(sid, s)


@app.post("/api/sesiones/{sid}/comandos")
def ejecutar_comando(sid: str, datos: dict = Body(...)):
    s, candado = _sesion(sid)
    try:
        comando = comando_desde_json(datos)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    with candado:
        s.ejecutar(comando)
        return _serializar(sid, s)


@app.post("/api/sesiones/{sid}/deshacer")
def deshacer(sid: str):
    s, candado = _sesion(sid)
    with candado:
        s.deshacer()
        return _serializar(sid, s)


@app.post("/api/sesiones/{sid}/rehacer")
def rehacer(sid: str):
    s, candado = _sesion(sid)
    with candado:
        s.rehacer()
        return _serializar(sid, s)


def _parsear_filtros(f: str) -> tuple:
    """'municipio:1,2;precio:0' → (('municipio',(1,2)),('precio',(0,)))"""
    filtros = {}
    for parte in filter(None, f.split(";")):
        nombre, codigos = parte.split(":")
        filtros[nombre] = tuple(sorted(int(c) for c in codigos.split(",")))
    return tuple(sorted(filtros.items()))


@app.get("/api/catalogo")
def catalogo(perfil: str = "optimizado", categoria: int = 1, orden: str = "precio_asc",
             f: str = "", pagina: int | None = Query(default=None), cursor: int | None = None):
    """Endpoint sin estado (usado por las pruebas de carga)."""
    motor = _motor(perfil)
    consulta = Consulta(categoria_id=categoria, filtros=_parsear_filtros(f), orden=orden)
    t0 = time.perf_counter()
    if pagina is not None and perfil == "base":
        p = motor.pagina_offset(consulta, pagina)
        cuerpo = {"productos": p.productos, "hay_mas": p.hay_mas, "siguiente": pagina + 1}
    elif cursor is not None and perfil == "optimizado":
        p = motor.pagina_cursor(consulta, cursor)
        cuerpo = {"productos": p.productos, "hay_mas": p.hay_mas, "siguiente": p.cursor}
    else:
        v, it = motor.vista(consulta)
        estado = it.estado()[0]
        cuerpo = {"productos": v.productos, "total": v.total, "facetas": v.conteo_facetas,
                  "hay_mas": v.hay_mas, "siguiente": estado}
    cuerpo["servidor_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return cuerpo


@app.post("/api/inventario/simular")
def simular_inventario(datos: dict = Body(default={})):
    """Publica eventos de inventario aleatorios (Observer)."""
    tipo = datos.get("tipo", "nuevo_lote")
    cantidad = max(1, min(int(datos.get("cantidad", 20)), 2000))
    con = MOTORES["base"].conexiones.get()
    max_id = con.execute("SELECT MAX(id) FROM productos").fetchone()[0]
    t0 = time.perf_counter()
    for _ in range(cantidad):
        if tipo == "nuevo_lote":
            publicador.registrar_lote(fila_aleatoria(_rng, _hojas))
        elif tipo == "agotado":
            publicador.agotar(_rng.randint(1, max_id))
        elif tipo == "cambio_precio":
            publicador.cambiar_precio(_rng.randint(1, max_id), _rng.randint(10, 400) * 50)
        else:
            raise HTTPException(400, "tipo debe ser nuevo_lote, agotado o cambio_precio")
    ms = (time.perf_counter() - t0) * 1000
    return {"tipo": tipo, "cantidad": cantidad, "tiempo_total_ms": round(ms, 1),
            "ms_por_evento": round(ms / cantidad, 3), "version_indice": MOTORES["optimizado"].version}


@app.get("/api/metricas")
def metricas():
    salida = {}
    for perfil, lat in LATENCIAS.items():
        datos = sorted(lat)
        if not datos:
            salida[perfil] = {"n": 0}
            continue
        p95 = datos[min(len(datos) - 1, int(0.95 * len(datos)))]
        salida[perfil] = {"n": len(datos), "p50_ms": round(statistics.median(datos), 2),
                          "p95_ms": round(p95, 2)}
    return salida
