"""Definición del dominio del catálogo de AgroConecta.

Árbol de categorías, precios de referencia (sintéticos), municipios del Oriente
Antioqueño y definición de las facetas por las que navega el comprador.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# --------------------------------------------------------------------------
# Árbol de categorías (raíz → familia → subfamilia → producto)
# --------------------------------------------------------------------------
ARBOL: dict[str, dict[str, list[str]]] = {
    "Frutas": {
        "Cítricos": ["Naranja Valencia", "Mandarina Oneco", "Limón Tahití"],
        "Bayas": ["Mora de Castilla", "Fresa", "Uchuva", "Arándano"],
        "Tropicales": ["Aguacate Hass", "Maracuyá", "Lulo", "Tomate de árbol",
                       "Granadilla", "Banano"],
    },
    "Hortalizas": {
        "De hoja": ["Lechuga Batavia", "Espinaca", "Acelga", "Repollo", "Cilantro"],
        "De raíz": ["Zanahoria", "Remolacha", "Rábano"],
        "De fruto": ["Tomate chonto", "Pimentón", "Pepino cohombro", "Ahuyama"],
        "De bulbo": ["Cebolla cabezona", "Cebolla junca", "Ajo"],
    },
    "Tubérculos": {
        "Papas": ["Papa capira", "Papa criolla", "Papa pastusa"],
        "Raíces": ["Yuca", "Arracacha"],
    },
    "Granos y legumbres": {
        "Frescos": ["Frijol cargamanto", "Arveja verde", "Maíz tierno"],
    },
    "Aromáticas": {
        "Hierbas": ["Albahaca", "Hierbabuena", "Tomillo", "Romero"],
    },
}

# Precio de referencia por kg en pesos colombianos (valores sintéticos).
PRECIO_BASE: dict[str, int] = {
    "Naranja Valencia": 2500, "Mandarina Oneco": 3500, "Limón Tahití": 3000,
    "Mora de Castilla": 5000, "Fresa": 7000, "Uchuva": 8000, "Arándano": 28000,
    "Aguacate Hass": 7500, "Maracuyá": 4500, "Lulo": 5000, "Tomate de árbol": 3500,
    "Granadilla": 6000, "Banano": 2200,
    "Lechuga Batavia": 2500, "Espinaca": 6000, "Acelga": 3000, "Repollo": 1500,
    "Cilantro": 6000, "Zanahoria": 1800, "Remolacha": 2000, "Rábano": 3000,
    "Tomate chonto": 3200, "Pimentón": 4500, "Pepino cohombro": 2000, "Ahuyama": 1800,
    "Cebolla cabezona": 2800, "Cebolla junca": 3000, "Ajo": 12000,
    "Papa capira": 1800, "Papa criolla": 3500, "Papa pastusa": 2000,
    "Yuca": 2000, "Arracacha": 3000,
    "Frijol cargamanto": 9000, "Arveja verde": 6000, "Maíz tierno": 2500,
    "Albahaca": 15000, "Hierbabuena": 12000, "Tomillo": 18000, "Romero": 16000,
}

# Municipios del Oriente Antioqueño y distancia aproximada a Medellín (km).
MUNICIPIOS: dict[str, float] = {
    "Guarne": 25, "El Retiro": 33, "Rionegro": 40, "La Ceja": 41, "Marinilla": 47,
    "El Carmen de Viboral": 54, "San Vicente": 55, "El Santuario": 57,
    "La Unión": 57, "El Peñol": 68, "Granada": 77, "Guatapé": 79, "Cocorná": 81,
    "Abejorral": 87, "Sonsón": 113,
}

CALIDADES = ["Primera", "Segunda", "Industrial"]
ORGANICO = ["Convencional", "Orgánico certificado"]

FINCAS = [
    "La Esperanza", "El Porvenir", "San José", "La Palma", "El Recreo", "Buenavista",
    "La Pradera", "El Mirador", "Santa Ana", "Los Naranjos", "La Cabaña", "Villa María",
    "La Fortuna", "El Edén", "Monteverde", "La Primavera", "Los Alpes", "El Paraíso",
    "La Florida", "Altamira",
]


# --------------------------------------------------------------------------
# Facetas: cada valor tiene un código entero (para el índice en memoria) y un
# predicado SQL (para la línea base). Ambos deben ser equivalentes.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Faceta:
    nombre: str                       # clave técnica
    etiqueta: str                     # texto visible
    valores: list[str]                # etiquetas de cada código 0..k-1
    expr_sql: str                     # expresión SQL que devuelve el código
    predicados_sql: list[tuple[str, tuple]] = field(default_factory=list)
    codificar: Callable[[dict], int] = lambda fila: 0


def _cubeta(valor: float, limites: list[float]) -> int:
    for i, lim in enumerate(limites):
        if valor < lim:
            return i
    return len(limites)


_MUNI = list(MUNICIPIOS)
_PRECIO_LIM = [2000, 4000, 8000]
_FRESCURA_LIM = [2, 5]  # 0-1 días, 2-4 días, 5+ días

FACETAS: list[Faceta] = [
    Faceta(
        "municipio", "Municipio de origen", _MUNI,
        "CASE municipio " + " ".join(f"WHEN '{m}' THEN {i}" for i, m in enumerate(_MUNI)) + " END",
        [("municipio = ?", (m,)) for m in _MUNI],
        lambda f: _MUNI.index(f["municipio"]),
    ),
    Faceta(
        "calidad", "Calidad", CALIDADES,
        "CASE calidad " + " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(CALIDADES)) + " END",
        [("calidad = ?", (c,)) for c in CALIDADES],
        lambda f: CALIDADES.index(f["calidad"]),
    ),
    Faceta(
        "organico", "Producción", ORGANICO,
        "organico",
        [("organico = ?", (0,)), ("organico = ?", (1,))],
        lambda f: int(f["organico"]),
    ),
    Faceta(
        "precio", "Precio por kg",
        ["Menos de $2.000", "$2.000 a $3.999", "$4.000 a $7.999", "$8.000 o más"],
        "CASE WHEN precio < 2000 THEN 0 WHEN precio < 4000 THEN 1 WHEN precio < 8000 THEN 2 ELSE 3 END",
        [("precio < ?", (2000,)), ("(precio >= ? AND precio < ?)", (2000, 4000)),
         ("(precio >= ? AND precio < ?)", (4000, 8000)), ("precio >= ?", (8000,))],
        lambda f: _cubeta(f["precio"], _PRECIO_LIM),
    ),
    Faceta(
        "frescura", "Días desde la cosecha",
        ["Hoy o ayer", "2 a 4 días", "5 días o más"],
        "CASE WHEN dias_cosecha < 2 THEN 0 WHEN dias_cosecha < 5 THEN 1 ELSE 2 END",
        [("dias_cosecha < ?", (2,)), ("(dias_cosecha >= ? AND dias_cosecha < ?)", (2, 5)),
         ("dias_cosecha >= ?", (5,))],
        lambda f: _cubeta(f["dias_cosecha"], _FRESCURA_LIM),
    ),
]

FACETAS_POR_NOMBRE = {f.nombre: f for f in FACETAS}

TAMANO_PAGINA = 24
