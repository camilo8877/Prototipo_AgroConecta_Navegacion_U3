"""Evaluación del prototipo: línea base vs optimizado (escenarios E1–E7).

Uso:  python -m scripts.benchmark            (desde la raíz del proyecto)
Deja los resultados en resultados/benchmark.json.
"""
from __future__ import annotations

import json
import platform
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.catalogo_def import FACETAS  # noqa: E402
from app.datos import fila_aleatoria, hojas_desde_db, obtener_catalogo  # noqa: E402
from app.motores.linea_base import MotorLineaBase  # noqa: E402
from app.motores.optimizado import MotorOptimizado  # noqa: E402
from app.patrones.command_navegacion import (AlternarFiltro, CambiarOrden,  # noqa: E402
                                             SeleccionarCategoria, SesionNavegacion)
from app.patrones.modelos import Consulta  # noqa: E402
from app.patrones.observer_inventario import EventoInventario, PublicadorInventario  # noqa: E402
from app.patrones.strategy_orden import ORDENES  # noqa: E402
from app.patrones.strategy_recorrido import ExtraccionDirecta, RecorridoOrdenado  # noqa: E402

TAMANOS = [10_000, 50_000, 200_000]
SALIDA = RAIZ / "resultados" / "benchmark.json"


def pct(datos, p):
    d = sorted(datos)
    return d[min(len(d) - 1, int(round(p / 100 * (len(d) - 1))))]


def resumen(datos):
    return {"n": len(datos), "media": statistics.fmean(datos), "p50": pct(datos, 50),
            "p95": pct(datos, 95), "max": max(datos)}


def consultas_realistas(arbol, n, semilla=5):
    """Navegaciones típicas: categoría a distintas profundidades + 0 a 3 facetas."""
    rng = random.Random(semilla)
    nodos = list(arbol.por_id.values())
    salida = []
    for _ in range(n):
        filtros = {}
        for f in rng.sample(FACETAS, rng.choice([0, 1, 1, 2, 2, 3])):
            filtros[f.nombre] = tuple(sorted(rng.sample(range(len(f.valores)), 1 if rng.random() < .7 else 2)))
        salida.append(Consulta(categoria_id=rng.choice(nodos).id, filtros=tuple(sorted(filtros.items())),
                               orden=rng.choice(list(ORDENES))))
    return salida


def medir_vistas(motor, consultas):
    tiempos = []
    for c in consultas:
        t0 = time.perf_counter()
        motor.vista(c)
        tiempos.append((time.perf_counter() - t0) * 1000)
    return tiempos


# ---------------------------------------------------------------------------
def e1_escalabilidad():
    print("E1 · escalabilidad con el tamaño del catálogo")
    res = {}
    for n in TAMANOS:
        ruta, ruta_idx = obtener_catalogo(n), obtener_catalogo(n, con_indices=True)
        motores = {"base": MotorLineaBase(ruta), "base_indices": MotorLineaBase(ruta_idx),
                   "optimizado": MotorOptimizado(ruta)}
        consultas = consultas_realistas(motores["base"].arbol, 120)
        res[n] = {}
        for nombre, m in motores.items():
            medir_vistas(m, consultas[:10])                       # calentamiento
            res[n][nombre] = resumen(medir_vistas(m, consultas))
            print(f"  n={n:>7} {nombre:<13} p50={res[n][nombre]['p50']:8.2f} ms  p95={res[n][nombre]['p95']:8.2f} ms")
        res[n]["indice"] = {"memoria_mb": motores["optimizado"].indice.memoria_mb(),
                            "construccion_ms": motores["optimizado"].indice.tiempo_construccion_ms,
                            "db_mb": ruta.stat().st_size / 1_048_576}
    return res


def e2_profundidad():
    print("E2 · costo de la página k (OFFSET vs cursor), 200.000 productos")
    ruta = obtener_catalogo(200_000)
    base, opt = MotorLineaBase(ruta), MotorOptimizado(ruta)
    paginas = [1, 10, 50, 100, 250, 500]
    escenarios = {"catalogo_completo": Consulta(), "frutas": Consulta(categoria_id=2, orden="frescura")}
    res = {}
    for nombre, c in escenarios.items():
        res[nombre] = {"paginas": paginas, "offset": [], "cursor": []}
        for k in paginas:
            tb = [base.pagina_offset(c, k - 1).tiempo_ms for _ in range(5)]
            it = opt.crear_iterador(c)
            for _ in range(k - 1):
                next(it)
            cursor = it.cursor
            to = [opt.pagina_cursor(c, cursor).tiempo_ms for _ in range(5)]
            res[nombre]["offset"].append(statistics.median(tb))
            res[nombre]["cursor"].append(statistics.median(to))
            print(f"  {nombre:<18} página {k:>3}: offset {statistics.median(tb):7.2f} ms · cursor {statistics.median(to):5.2f} ms")
    return res


def e3_planificador():
    print("E3 · estrategias de recorrido según selectividad (200.000 productos)")
    ruta = obtener_catalogo(200_000)
    opt = MotorOptimizado(ruta)
    idx = opt.indice
    rng = np.random.default_rng(3)
    vivos = np.flatnonzero(idx.existe)
    fracciones = [0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0]
    orden = ORDENES["precio_asc"]
    claves, ids = idx.ordenes["precio_asc"]
    clave_de = lambda a: orden.clave_vector(idx.cols, a)  # noqa: E731
    estrategias = {"recorrido": RecorridoOrdenado(), "extraccion": ExtraccionDirecta()}
    res = {"fracciones": fracciones, "m": [], "recorrido": [], "extraccion": [], "adaptativo": [], "elegida": []}
    for fr in fracciones:
        filtro = np.zeros(idx.capacidad, bool)
        m = max(1, int(len(vivos) * fr))
        filtro[rng.choice(vivos, m, replace=False)] = True
        res["m"].append(m)
        for nombre, est in estrategias.items():
            ts = []
            for _ in range(15):
                t0 = time.perf_counter()
                est.pagina(filtro, claves, ids, clave_de, None, 24)
                ts.append((time.perf_counter() - t0) * 1000)
            res[nombre].append(statistics.median(ts))
        elegida = opt.planificador.elegir(m, len(ids), 24)
        res["elegida"].append(elegida.nombre)
        res["adaptativo"].append(res["recorrido" if elegida.nombre.startswith("recorrido") else "extraccion"][-1])
        print(f"  {fr:7.2%} (m={m:>6}): recorrido {res['recorrido'][-1]:7.3f} ms · extracción "
              f"{res['extraccion'][-1]:6.3f} ms → elige {elegida.nombre}")

    # Casos reales en los que el filtro está correlacionado con el orden.
    print("  Casos correlacionados (filtro real + orden):")
    casos = {
        "Arándano · menor precio": Consulta(categoria_id=opt.arbol.raiz.id,
                                            filtros=(("precio", (3,)),), orden="precio_asc"),
        "Sonsón · más cercano": Consulta(filtros=(("municipio", (14,)),), orden="cercania"),
        "5+ días · más fresco": Consulta(filtros=(("frescura", (2,)),), orden="frescura"),
    }
    arandano = next(h for h in opt.arbol.raiz.hojas() if h.nombre == "Arándano")
    casos["Arándano · menor precio"] = Consulta(categoria_id=arandano.id, orden="precio_asc")
    res["correlacionados"] = {}
    for nombre, c in casos.items():
        fila = {}
        filtro = opt.filtro(c)
        m = int(np.count_nonzero(filtro))
        cl, ii = idx.ordenes[c.orden]
        o = ORDENES[c.orden]
        cd = lambda a, o=o: o.clave_vector(idx.cols, a)  # noqa: E731
        ejecutores = {
            "recorrido": lambda: RecorridoOrdenado().pagina(filtro, cl, ii, cd, None, 24),
            "extraccion": lambda: ExtraccionDirecta().pagina(filtro, cl, ii, cd, None, 24),
            "adaptativo": lambda: opt.planificador.ejecutar(filtro, cl, ii, cd, None, 24, m),
        }
        for etiqueta, fn in ejecutores.items():
            ts = []
            for _ in range(25):
                t0 = time.perf_counter()
                r = fn()
                ts.append((time.perf_counter() - t0) * 1000)
            fila[etiqueta] = statistics.median(ts)
        fila["elegida"] = r[1]
        fila["m"] = m
        res["correlacionados"][nombre] = fila
        print(f"    {nombre:<26} m={fila['m']:>6} recorrido {fila['recorrido']:6.2f} · extracción "
              f"{fila['extraccion']:5.2f} · adaptativo {fila['adaptativo']:5.2f} ms ({fila['elegida']})")
    return res


def e4_consistencia():
    print("E4 · consistencia de la paginación con inventario cambiando (50.000 productos)")
    escenarios = {"llegan_lotes": (4, 0), "se_agotan_vistos": (0, 4)}
    res = {}
    for esc, (n_ins, n_ago) in escenarios.items():
        res[esc] = {}
        for perfil in ("base", "optimizado"):
            tmp = Path(tempfile.mkdtemp()) / "c.db"
            shutil.copy(obtener_catalogo(50_000), tmp)
            pub = PublicadorInventario(tmp)
            motor = MotorLineaBase(tmp) if perfil == "base" else MotorOptimizado(tmp, pub)
            hojas = hojas_desde_db(motor.conexiones.get())
            rng = random.Random(9)
            c = Consulta(orden="precio_asc")
            inicial = [p["id"] for pag in motor.crear_iterador(c) for p in pag.productos]
            it = motor.crear_iterador(c)
            vistos, agotados = [], set()
            for _ in range(20):
                pag = next(it)
                vistos += [p["id"] for p in pag.productos]
                for _ in range(n_ins):       # llegan lotes más baratos que lo ya visto
                    f = list(fila_aleatoria(rng, hojas))
                    f[4] = rng.randint(2, 6) * 50
                    f[9] = 100
                    pub.registrar_lote(tuple(f))
                for _ in range(n_ago):       # se agotan lotes que el comprador ya vio
                    i = rng.choice([v for v in vistos if v not in agotados])
                    agotados.add(i)
                    pub.agotar(i)
            pos = {i: k for k, i in enumerate(inicial)}
            frontera = max(pos[i] for i in vistos if i in pos)
            esperados = [i for i in inicial[: frontera + 1] if i not in agotados or i in vistos]
            duplicados = len(vistos) - len(set(vistos))
            omitidos = len(set(esperados) - set(vistos))
            res[esc][perfil] = {"mostrados": len(vistos), "duplicados": duplicados, "omitidos": omitidos}
            print(f"  {esc:<17} {perfil:<11} mostrados={len(vistos)} duplicados={duplicados} omitidos={omitidos}")
            pub.cerrar()
    return res


def e5_callejones():
    print("E5 · callejones sin salida: filtros a ciegas vs facetas con conteo (50.000 productos)")
    opt = MotorOptimizado(obtener_catalogo(50_000))
    res = {}
    for modo in ("a_ciegas", "guiada"):
        rng = random.Random(21)
        sesiones, con_callejon, callejones, clics = 1000, 0, 0, 0
        for _ in range(sesiones):
            c = Consulta()
            hubo = False
            refinamientos = 0
            while refinamientos < 4:
                v, _ = opt.vista(c)
                nodo = opt.arbol.nodo(c.categoria_id)
                opciones = []
                for h in getattr(nodo, "hijos", []):
                    if modo == "a_ciegas" or h.contar(v.conteo_hojas) > 0:
                        opciones.append(("cat", h.id))
                elegidas = c.filtros_dict()
                for f in FACETAS:
                    if f.nombre in elegidas:
                        continue
                    for cod, n in enumerate(v.conteo_facetas[f.nombre]):
                        if modo == "a_ciegas" or n > 0:
                            opciones.append((f.nombre, cod))
                tipo, val = rng.choice(opciones)
                nueva = c.con_categoria(val) if tipo == "cat" else c.alternar_filtro(tipo, val)
                clics += 1
                if opt.vista(nueva)[0].total == 0:
                    callejones += 1
                    hubo = True
                    clics += 1          # el comprador tiene que volver atrás
                    continue
                c = nueva
                refinamientos += 1
            con_callejon += hubo
        res[modo] = {"sesiones": sesiones, "pct_sesiones_con_callejon": 100 * con_callejon / sesiones,
                     "callejones_por_sesion": callejones / sesiones, "clics_por_sesion": clics / sesiones}
        print(f"  {modo:<9} sesiones con callejón={res[modo]['pct_sesiones_con_callejon']:.1f} % "
              f"clics/sesión={res[modo]['clics_por_sesion']:.2f}")
    return res


def e6_deshacer():
    print("E6 · volver atrás (Command): nueva consulta vs memento (200.000 productos)")
    ruta = obtener_catalogo(200_000)
    res = {}
    for nombre, motor in (("base", MotorLineaBase(ruta)), ("optimizado", MotorOptimizado(ruta))):
        tiempos = []
        for rep in range(5):
            s = SesionNavegacion(motor)
            for cmd in (SeleccionarCategoria(19), AlternarFiltro("calidad", 0), AlternarFiltro("municipio", 2),
                        CambiarOrden("frescura"), AlternarFiltro("frescura", 0)):
                s.ejecutar(cmd)
            while s.deshacer():
                tiempos.append(s.ultima_operacion["tiempo_ms"])
        res[nombre] = resumen(tiempos)
        print(f"  {nombre:<11} p50={res[nombre]['p50']:.3f} ms  p95={res[nombre]['p95']:.3f} ms")
    return res


def e7_eventos():
    print("E7 · mantenimiento del índice por eventos vs reconstrucción (200.000 productos)")
    tmp = Path(tempfile.mkdtemp()) / "c.db"
    shutil.copy(obtener_catalogo(200_000), tmp)
    opt = MotorOptimizado(tmp)
    idx = opt.indice
    hojas = hojas_desde_db(opt.conexiones.get())
    rng = random.Random(4)
    from app.patrones.observer_inventario import COLUMNAS
    siguiente = int(np.flatnonzero(idx.existe).max()) + 1
    res = {}
    for tipo in ("agotado", "cambio_precio", "nuevo_lote"):
        ts = []
        for _ in range(300):
            if tipo == "nuevo_lote":
                ev = EventoInventario(tipo, siguiente, dict(zip(COLUMNAS, fila_aleatoria(rng, hojas))))
                siguiente += 1
            elif tipo == "agotado":
                ev = EventoInventario(tipo, rng.randint(1, 200_000))
            else:
                ev = EventoInventario(tipo, rng.randint(1, 200_000), {"precio": rng.randint(10, 400) * 50})
            t0 = time.perf_counter()
            idx.actualizar(ev)
            ts.append((time.perf_counter() - t0) * 1000)
        res[tipo] = resumen(ts)
        print(f"  {tipo:<14} p50={res[tipo]['p50']:.3f} ms")
    t0 = time.perf_counter()
    MotorOptimizado(tmp)
    res["reconstruccion_ms"] = (time.perf_counter() - t0) * 1000
    print(f"  reconstrucción completa: {res['reconstruccion_ms']:.0f} ms")
    return res


if __name__ == "__main__":
    t0 = time.time()
    resultados = {
        "entorno": {"python": platform.python_version(), "so": platform.platform(),
                    "nucleos": __import__("os").cpu_count(), "numpy": np.__version__},
        "E1": e1_escalabilidad(), "E2": e2_profundidad(), "E3": e3_planificador(),
        "E4": e4_consistencia(), "E5": e5_callejones(), "E6": e6_deshacer(), "E7": e7_eventos(),
    }
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps(resultados, indent=2, ensure_ascii=False, default=str))
    print(f"Listo en {time.time() - t0:.0f} s → {SALIDA}")
