"""Patrón Composite: árbol de categorías del catálogo.

Una categoría compuesta (Frutas, Bayas…) y una categoría hoja (Mora de Castilla)
se tratan de forma uniforme: ambas saben listar sus hojas, contar productos y
describir su ruta (migas de pan). El cliente no distingue entre ellas.
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from typing import Callable, Iterator, Mapping


class NodoCategoria(ABC):
    """Componente del Composite."""

    def __init__(self, id_: int, nombre: str, padre: "CategoriaCompuesta | None" = None):
        self.id = id_
        self.nombre = nombre
        self.padre = padre

    @abstractmethod
    def hojas(self) -> list["CategoriaHoja"]: ...

    @abstractmethod
    def contar(self, conteo_hojas: Mapping[int, int]) -> int:
        """Número de productos bajo este nodo dado el conteo por hoja."""

    @abstractmethod
    def a_dict(self, conteo_hojas: Mapping[int, int], profundidad: int = 9) -> dict: ...

    def ruta(self) -> list["NodoCategoria"]:
        nodo, camino = self, []
        while nodo is not None:
            camino.append(nodo)
            nodo = nodo.padre
        return list(reversed(camino))

    def ancestros(self) -> Iterator["CategoriaCompuesta"]:
        nodo = self.padre
        while nodo is not None:
            yield nodo
            nodo = nodo.padre

    def es_hoja(self) -> bool:
        return False


class CategoriaHoja(NodoCategoria):
    """Hoja del Composite: un producto concreto (p. ej. Mora de Castilla)."""

    def hojas(self) -> list["CategoriaHoja"]:
        return [self]

    def contar(self, conteo_hojas: Mapping[int, int]) -> int:
        return int(conteo_hojas.get(self.id, 0))

    def a_dict(self, conteo_hojas: Mapping[int, int], profundidad: int = 9) -> dict:
        return {"id": self.id, "nombre": self.nombre, "conteo": self.contar(conteo_hojas), "hijos": []}

    def es_hoja(self) -> bool:
        return True


class CategoriaCompuesta(NodoCategoria):
    """Compuesto: agrupa categorías hijas y delega en ellas."""

    def __init__(self, id_: int, nombre: str, padre: "CategoriaCompuesta | None" = None):
        super().__init__(id_, nombre, padre)
        self.hijos: list[NodoCategoria] = []
        self._hojas_cache: list[CategoriaHoja] | None = None

    def agregar(self, hijo: NodoCategoria) -> None:
        hijo.padre = self
        self.hijos.append(hijo)
        self._hojas_cache = None

    def hojas(self) -> list[CategoriaHoja]:
        if self._hojas_cache is None:
            self._hojas_cache = [h for hijo in self.hijos for h in hijo.hojas()]
        return self._hojas_cache

    def contar(self, conteo_hojas: Mapping[int, int]) -> int:
        return sum(hijo.contar(conteo_hojas) for hijo in self.hijos)

    def a_dict(self, conteo_hojas: Mapping[int, int], profundidad: int = 9) -> dict:
        hijos = [h.a_dict(conteo_hojas, profundidad - 1) for h in self.hijos] if profundidad > 0 else []
        return {"id": self.id, "nombre": self.nombre, "conteo": self.contar(conteo_hojas), "hijos": hijos}


class ArbolCategorias:
    """Construye el Composite desde la tabla `categorias` y ofrece búsquedas."""

    def __init__(self, raiz: CategoriaCompuesta, por_id: dict[int, NodoCategoria]):
        self.raiz = raiz
        self.por_id = por_id

    @classmethod
    def desde_db(cls, con: sqlite3.Connection) -> "ArbolCategorias":
        filas = con.execute("SELECT id, nombre, padre_id FROM categorias ORDER BY id").fetchall()
        padres = {padre for _, _, padre in filas if padre is not None}
        por_id: dict[int, NodoCategoria] = {}
        for id_, nombre, _ in filas:
            por_id[id_] = CategoriaCompuesta(id_, nombre) if id_ in padres else CategoriaHoja(id_, nombre)
        raiz = None
        for id_, _, padre in filas:
            if padre is None:
                raiz = por_id[id_]
            else:
                por_id[padre].agregar(por_id[id_])  # type: ignore[union-attr]
        assert isinstance(raiz, CategoriaCompuesta)
        return cls(raiz, por_id)

    def nodo(self, id_: int) -> NodoCategoria:
        return self.por_id[id_]

    @property
    def max_id(self) -> int:
        return max(self.por_id)

    def recorrer(self, visitar: Callable[[NodoCategoria], None], nodo: NodoCategoria | None = None) -> None:
        nodo = nodo or self.raiz
        visitar(nodo)
        for hijo in getattr(nodo, "hijos", []):
            self.recorrer(visitar, hijo)
