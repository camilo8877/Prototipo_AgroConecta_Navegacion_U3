"""Patrón Strategy: criterios de ordenamiento del catálogo.

Cada estrategia sabe (1) cómo ordenar en SQL para la línea base y (2) cómo
construir una clave compuesta entera, única y estable — (criterio, id) — que
permite paginar por cursor en el motor optimizado. Agregar un criterio nuevo
no modifica ni el motor ni la interfaz (principio abierto/cerrado).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

MULT = 10_000_000  # clave = parte * MULT + id  (id < 10 millones)


class EstrategiaOrden(ABC):
    nombre: str
    etiqueta: str
    sql: str

    @abstractmethod
    def parte(self, precio, dias, distancia_dm):
        """Componente principal de la clave (escalar o vector numpy)."""

    def clave_vector(self, cols: dict[str, np.ndarray], ids: np.ndarray) -> np.ndarray:
        p = self.parte(cols["precio"][ids].astype(np.int64), cols["dias"][ids].astype(np.int64),
                       cols["distancia_dm"][ids].astype(np.int64))
        return p * MULT + ids.astype(np.int64)

    def clave_fila(self, precio: int, dias: int, distancia_dm: int, id_: int) -> int:
        return int(self.parte(precio, dias, distancia_dm)) * MULT + int(id_)


class MenorPrecio(EstrategiaOrden):
    nombre, etiqueta, sql = "precio_asc", "Menor precio", "precio ASC, id ASC"

    def parte(self, precio, dias, distancia_dm):
        return precio


class MayorPrecio(EstrategiaOrden):
    nombre, etiqueta, sql = "precio_desc", "Mayor precio", "precio DESC, id ASC"

    def parte(self, precio, dias, distancia_dm):
        return 1_000_000 - precio


class MasFresco(EstrategiaOrden):
    nombre, etiqueta, sql = "frescura", "Más fresco", "dias_cosecha ASC, id ASC"

    def parte(self, precio, dias, distancia_dm):
        return dias


class MasCercano(EstrategiaOrden):
    nombre, etiqueta, sql = "cercania", "Más cercano a Medellín", "distancia_km ASC, id ASC"

    def parte(self, precio, dias, distancia_dm):
        return distancia_dm


ORDENES: dict[str, EstrategiaOrden] = {e.nombre: e for e in
                                       (MenorPrecio(), MayorPrecio(), MasFresco(), MasCercano())}
