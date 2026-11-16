"""Prueba de carga HTTP: usuarios virtuales concurrentes navegando el catálogo.

Cada usuario virtual es un hilo con su propio cliente HTTP persistente que, en
ciclo cerrado, hace un 70 % de consultas nuevas (categoría + filtros + orden)
y un 30 % de «página siguiente» sobre su última consulta.

Uso (con el servidor corriendo con CATALOGO_N=200000):
    python -m scripts.prueba_carga --usuarios 5 10 25 50 --segundos 15
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import threading
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.catalogo_def import FACETAS  # noqa: E402
from app.patrones.strategy_orden import ORDENES  # noqa: E402

N_CATEGORIAS = 57


def parametros_aleatorios(rng: random.Random) -> dict:
    filtros = []
    for f in rng.sample(FACETAS, rng.choice([0, 1, 1, 2, 2, 3])):
        cods = sorted(rng.sample(range(len(f.valores)), 1 if rng.random() < .7 else 2))
        filtros.append(f"{f.nombre}:{','.join(map(str, cods))}")
    return {"categoria": rng.randint(1, N_CATEGORIAS), "orden": rng.choice(list(ORDENES)),
            "f": ";".join(filtros)}


def usuario(url, perfil, fin, calentamiento, registros, semilla):
    rng = random.Random(semilla)
    ultima, siguiente = None, None
    with httpx.Client(base_url=url, timeout=30) as cliente:
        while time.perf_counter() < fin:
            if ultima and siguiente is not None and rng.random() < 0.3:
                params = dict(ultima)
                params["pagina" if perfil == "base" else "cursor"] = siguiente
                tipo = "pagina"
            else:
                params = parametros_aleatorios(rng)
                ultima, tipo = params, "vista"
            params["perfil"] = perfil
            t0 = time.perf_counter()
            try:
                r = cliente.get("/api/catalogo", params=params)
                ok = r.status_code == 200
                if ok:
                    cuerpo = r.json()
                    siguiente = cuerpo.get("siguiente") if cuerpo.get("hay_mas") else None
            except httpx.HTTPError:
                ok = False
            t1 = time.perf_counter()
            if t0 >= calentamiento:
                registros.append((tipo, (t1 - t0) * 1000, ok))


def ejecutar(url, perfil, usuarios, segundos, calentamiento=3):
    registros: list = []
    inicio = time.perf_counter()
    fin_cal = inicio + calentamiento
    fin = fin_cal + segundos
    hilos = [threading.Thread(target=usuario, args=(url, perfil, fin, fin_cal, registros, i))
             for i in range(usuarios)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    lat = sorted(x[1] for x in registros if x[2])
    errores = sum(1 for x in registros if not x[2])
    vistas = sorted(x[1] for x in registros if x[2] and x[0] == "vista")

    def p(d, q):
        return d[min(len(d) - 1, int(q * (len(d) - 1)))] if d else float("nan")

    return {"perfil": perfil, "usuarios": usuarios, "peticiones": len(registros),
            "rendimiento_rps": len(lat) / segundos, "p50_ms": p(lat, .5), "p95_ms": p(lat, .95),
            "p95_vista_ms": p(vistas, .95), "media_ms": statistics.fmean(lat) if lat else float("nan"),
            "error_pct": 100 * errores / max(1, len(registros))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--usuarios", type=int, nargs="+", default=[5, 10, 25, 50])
    ap.add_argument("--segundos", type=int, default=15)
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "carga_http.json"))
    a = ap.parse_args()
    resultados = []
    for perfil in ("base", "optimizado"):
        for u in a.usuarios:
            r = ejecutar(a.url, perfil, u, a.segundos)
            resultados.append(r)
            print(f"{perfil:<11} {u:>3} usuarios: {r['rendimiento_rps']:7.1f} pet/s  p50 {r['p50_ms']:7.1f} ms  "
                  f"p95 {r['p95_ms']:7.1f} ms  error {r['error_pct']:.1f} %", flush=True)
    Path(a.salida).write_text(json.dumps(resultados, indent=2))
