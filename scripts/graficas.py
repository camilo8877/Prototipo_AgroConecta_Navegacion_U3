"""Genera las figuras del informe a partir de resultados/*.json."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "resultados"
FIG = RAIZ / "docs" / "figuras"
FIG.mkdir(parents=True, exist_ok=True)

# Paleta validada (scripts de dataviz): orden fijo por entidad, nunca por rango.
COLOR = {"base": "#c9711e", "base_indices": "#6a5ab8", "optimizado": "#0f8a5f"}
MARCA = {"base": "o", "base_indices": "s", "optimizado": "D"}
NOMBRE = {"base": "Línea base (SQL)", "base_indices": "Línea base + índices SQL", "optimizado": "Optimizado"}
TINTA, TINTA_2, REJILLA = "#1d2420", "#5d6761", "#e6e9e4"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": REJILLA, "axes.labelcolor": TINTA_2,
    "xtick.color": TINTA_2, "ytick.color": TINTA_2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": REJILLA, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "figure.dpi": 200,
})
fmt_ms = FuncFormatter(lambda v, _: (f"{v:g}".replace(".", ",")) + " ms")
fmt_miles = FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", "."))


def titulo(ax, t, sub=None):
    ax.set_title(t, loc="left", fontsize=12, color=TINTA, fontweight="bold", pad=18 if sub else 8)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=9, color=TINTA_2)


def etiqueta_final(ax, x, y, texto, color, dy=0):
    ax.annotate(texto, (x, y), xytext=(6, dy), textcoords="offset points", va="center",
                fontsize=9, color=TINTA)
    ax.plot([x], [y], marker="o", ms=0)  # ancla


def g1(b):
    e1 = b["E1"]
    tam = sorted(int(k) for k in e1)
    fig, ax = plt.subplots(figsize=(7.2, 4))
    for perfil in ("base", "base_indices", "optimizado"):
        ys = [e1[str(n)][perfil]["p95"] for n in tam]
        ax.plot(tam, ys, color=COLOR[perfil], lw=2, marker=MARCA[perfil], ms=7, label=NOMBRE[perfil])
        dy = {"base": -7, "base_indices": 7, "optimizado": 0}[perfil]
        ax.annotate(f"{ys[-1]:.1f} ms".replace(".", ","), (tam[-1], ys[-1]), xytext=(8, dy),
                    textcoords="offset points", va="center", fontsize=9, color=TINTA)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(fmt_ms)
    ax.set_xticks(tam)
    ax.xaxis.set_major_formatter(fmt_miles)
    ax.set_xlabel("Productos en el catálogo")
    ax.set_xlim(0, tam[-1] * 1.13)
    titulo(ax, "Latencia p95 de una vista del catálogo", "Primera página + total + conteos de 5 facetas y del árbol · escala logarítmica")
    ax.legend(loc="center right", bbox_to_anchor=(0.98, 0.42))
    fig.tight_layout()
    fig.savefig(FIG / "g1_escalabilidad.png")
    plt.close(fig)


def g2(b):
    e2 = b["E2"]["catalogo_completo"]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for clave, perfil, nombre in (("offset", "base", "LIMIT/OFFSET (línea base)"),
                                  ("cursor", "optimizado", "Cursor sobre índice ordenado")):
        ax.plot(e2["paginas"], e2[clave], color=COLOR[perfil], lw=2, marker=MARCA[perfil], ms=7, label=nombre)
        ax.annotate(f"{e2[clave][-1]:.2f} ms".replace(".", ","), (e2["paginas"][-1], e2[clave][-1]),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=TINTA)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(fmt_ms)
    ax.set_xlabel("Número de página (24 productos por página)")
    ax.set_xlim(-15, 570)
    titulo(ax, "Costo de pedir la página k", "Catálogo completo de 200.000 productos, orden por menor precio · escala logarítmica")
    ax.legend(loc="center right", bbox_to_anchor=(1, 0.55))
    fig.tight_layout()
    fig.savefig(FIG / "g2_profundidad.png")
    plt.close(fig)


def g3(b):
    e3 = b["E3"]
    x = [f * 100 for f in e3["fracciones"]]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.plot(x, e3["extraccion"], color=COLOR["base_indices"], lw=2, marker="s", ms=6, label="Extracción directa")
    ax.plot(x, e3["recorrido"], color=COLOR["base"], lw=2, marker="o", ms=6, label="Recorrido ordenado")
    ax.plot(x, e3["adaptativo"], color=COLOR["optimizado"], lw=0, marker="D", ms=9, mfc="none", mew=2,
            label="Elegida por el planificador")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(fmt_ms)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",") + " %"))
    ax.set_xlabel("Selectividad del filtro (% del catálogo que cumple)")
    titulo(ax, "Strategy: dos formas de armar la misma página", "200.000 productos · el planificador elige con un modelo de costo")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG / "g3_planificador.png")
    plt.close(fig)


def g4(c):
    usuarios = sorted({r["usuarios"] for r in c})
    por = {(r["perfil"], r["usuarios"]): r for r in c}
    # (a) rendimiento: barras agrupadas
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ancho = 0.36
    for k, perfil in enumerate(("base", "optimizado")):
        xs = [i + (k - 0.5) * (ancho + 0.04) for i in range(len(usuarios))]
        ys = [por[(perfil, u)]["rendimiento_rps"] for u in usuarios]
        ax.bar(xs, ys, width=ancho, color=COLOR[perfil], label=NOMBRE[perfil], edgecolor="white", linewidth=2)
        for xx, yy in zip(xs, ys):
            ax.annotate(f"{yy:.0f}", (xx, yy), xytext=(0, 3), textcoords="offset points", ha="center",
                        fontsize=8.5, color=TINTA)
    ax.set_xticks(range(len(usuarios)), [f"{u} usuarios" for u in usuarios])
    ax.set_ylabel("Peticiones por segundo")
    ax.grid(axis="x", visible=False)
    titulo(ax, "Rendimiento bajo carga concurrente (HTTP)", "200.000 productos · 70 % vistas nuevas y 30 % página siguiente")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG / "g4a_rendimiento.png")
    plt.close(fig)
    # (b) p95: líneas
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for perfil in ("base", "optimizado"):
        ys = [por[(perfil, u)]["p95_ms"] for u in usuarios]
        ax.plot(usuarios, ys, color=COLOR[perfil], lw=2, marker=MARCA[perfil], ms=7, label=NOMBRE[perfil])
        ax.annotate(f"{ys[-1]:,.0f} ms".replace(",", "."), (usuarios[-1], ys[-1]), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=9, color=TINTA)
    ax.axhline(1000, color=TINTA_2, lw=1, ls=(0, (4, 3)))
    ax.text(5, 1100, "1 s", fontsize=8.5, color=TINTA_2)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".") + " ms"))
    ax.set_xticks(usuarios)
    ax.set_xlim(0, usuarios[-1] * 1.18)
    ax.set_xlabel("Usuarios concurrentes")
    titulo(ax, "Latencia p95 bajo carga concurrente (HTTP)", "Escala logarítmica · incluye red local y serialización JSON")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(FIG / "g4b_latencia.png")
    plt.close(fig)


if __name__ == "__main__":
    bench = json.loads((RES / "benchmark.json").read_text())
    carga = json.loads((RES / "carga_http.json").read_text())
    g1(bench)
    g2(bench)
    g3(bench)
    g4(carga)
    print("Figuras en", FIG)
