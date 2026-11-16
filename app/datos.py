"""Generación determinista del catálogo sintético en SQLite.

La base de datos es la fuente de verdad (como el esquema del catalogo-service de
la Unidad 2). El motor optimizado construye a partir de ella su modelo de
lectura en memoria.
"""
from __future__ import annotations

import os
import random
import sqlite3
from pathlib import Path

from .catalogo_def import ARBOL, CALIDADES, FINCAS, MUNICIPIOS, PRECIO_BASE

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_DATOS = RAIZ / "data"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    padre_id INTEGER REFERENCES categorias(id)
);
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    municipio TEXT NOT NULL,
    finca TEXT NOT NULL,
    precio INTEGER NOT NULL,
    organico INTEGER NOT NULL,
    calidad TEXT NOT NULL,
    dias_cosecha INTEGER NOT NULL,
    distancia_km REAL NOT NULL,
    disponible_kg INTEGER NOT NULL
);
"""

# Índices secundarios: SOLO se crean en la configuración intermedia
# «línea base + índices SQL» para aislar su efecto en la evaluación.
INDICES_SQL = """
CREATE INDEX IF NOT EXISTS ix_prod_categoria ON productos(categoria_id);
CREATE INDEX IF NOT EXISTS ix_prod_municipio ON productos(municipio);
CREATE INDEX IF NOT EXISTS ix_prod_precio ON productos(precio, id);
CREATE INDEX IF NOT EXISTS ix_prod_dias ON productos(dias_cosecha, id);
CREATE INDEX IF NOT EXISTS ix_prod_distancia ON productos(distancia_km, id);
CREATE INDEX IF NOT EXISTS ix_prod_disponible ON productos(disponible_kg);
"""


def insertar_categorias(con: sqlite3.Connection) -> dict[str, int]:
    """Inserta el árbol y devuelve {nombre_hoja: id}."""
    hojas: dict[str, int] = {}
    con.execute("INSERT INTO categorias(id, nombre, padre_id) VALUES (1, 'Catálogo', NULL)")
    siguiente = 2
    for familia, subfamilias in ARBOL.items():
        id_fam = siguiente
        siguiente += 1
        con.execute("INSERT INTO categorias VALUES (?, ?, ?)", (id_fam, familia, 1))
        for sub, productos in subfamilias.items():
            id_sub = siguiente
            siguiente += 1
            con.execute("INSERT INTO categorias VALUES (?, ?, ?)", (id_sub, sub, id_fam))
            for prod in productos:
                con.execute("INSERT INTO categorias VALUES (?, ?, ?)", (siguiente, prod, id_sub))
                hojas[prod] = siguiente
                siguiente += 1
    return hojas


def fila_aleatoria(rng: random.Random, hojas: dict[str, int], nombre: str | None = None) -> tuple:
    """Genera un lote de producto realista (sin id)."""
    nombre = nombre or rng.choice(list(hojas))
    municipio = rng.choice(list(MUNICIPIOS))
    distancia = round(MUNICIPIOS[municipio] + rng.uniform(-6, 12), 1)
    calidad = rng.choices(CALIDADES, weights=[50, 35, 15])[0]
    factor_calidad = {"Primera": 1.15, "Segunda": 0.95, "Industrial": 0.7}[calidad]
    organico = 1 if rng.random() < (0.35 if nombre in ARBOL["Aromáticas"]["Hierbas"] else 0.15) else 0
    precio = int(PRECIO_BASE[nombre] * factor_calidad * (1.25 if organico else 1)
                 * rng.uniform(0.75, 1.3) / 50) * 50
    dias = min(10, int(rng.expovariate(1 / 2.6)))
    disponible = 0 if rng.random() < 0.08 else rng.randint(10, 800)
    finca = f"Finca {rng.choice(FINCAS)}"
    return (nombre, hojas[nombre], municipio, finca, precio, organico, calidad,
            dias, distancia, disponible)


def generar_catalogo(n: int, ruta: Path, semilla: int = 42, con_indices: bool = False) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        ruta.unlink()
    rng = random.Random(semilla)
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA)
    hojas = insertar_categorias(con)
    # Popularidad desigual: algunos productos tienen muchos más lotes (cola larga).
    nombres = list(hojas)
    pesos = [rng.paretovariate(1.2) for _ in nombres]
    lotes = (fila_aleatoria(rng, hojas, rng.choices(nombres, weights=pesos)[0]) for _ in range(n))
    con.executemany(
        "INSERT INTO productos(nombre, categoria_id, municipio, finca, precio, organico, "
        "calidad, dias_cosecha, distancia_km, disponible_kg) VALUES (?,?,?,?,?,?,?,?,?,?)",
        lotes,
    )
    if con_indices:
        con.executescript(INDICES_SQL)
    con.commit()
    con.execute("PRAGMA journal_mode=WAL")
    con.close()
    return ruta


def ruta_catalogo(n: int, con_indices: bool = False) -> Path:
    sufijo = "_idx" if con_indices else ""
    return CARPETA_DATOS / f"catalogo_{n}{sufijo}.db"


def obtener_catalogo(n: int, con_indices: bool = False, regenerar: bool = False) -> Path:
    """Devuelve la ruta del catálogo de tamaño n, generándolo si no existe."""
    ruta = ruta_catalogo(n, con_indices)
    if regenerar or not ruta.exists():
        generar_catalogo(n, ruta, con_indices=con_indices)
    return ruta


def hojas_desde_db(con: sqlite3.Connection) -> dict[str, int]:
    filas = con.execute(
        "SELECT c.nombre, c.id FROM categorias c WHERE NOT EXISTS "
        "(SELECT 1 FROM categorias h WHERE h.padre_id = c.id)"
    ).fetchall()
    return dict(filas)


if __name__ == "__main__":
    n = int(os.environ.get("CATALOGO_N", "50000"))
    print(obtener_catalogo(n, regenerar=True))
