"""Interfaz común de los motores de navegación (perfiles «línea base» y «optimizado»)."""
from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..catalogo_def import TAMANO_PAGINA
from ..patrones.composite_categorias import ArbolCategorias
from ..patrones.iterator_paginacion import IteradorPaginas
from ..patrones.modelos import Consulta, Pagina, VistaCatalogo

CAMPOS = ("id", "nombre", "categoria_id", "municipio", "finca", "precio", "organico",
          "calidad", "dias_cosecha", "distancia_km", "disponible_kg")


class ConexionesPorHilo:
    """Una conexión SQLite por hilo (los hilos del servidor no comparten cursores)."""

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._local = threading.local()

    def get(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.ruta, check_same_thread=False)
            con.execute("PRAGMA cache_size=-65536")   # 64 MB de caché por conexión
            self._local.con = con
        return con


class MotorCatalogo(ABC):
    perfil: str

    def __init__(self, ruta_db: Path, tam_pagina: int = TAMANO_PAGINA):
        self.ruta_db = ruta_db
        self.tam = tam_pagina
        self.conexiones = ConexionesPorHilo(ruta_db)
        self.arbol = ArbolCategorias.desde_db(self.conexiones.get())

    @property
    def version(self) -> int:
        return 0

    @abstractmethod
    def vista(self, consulta: Consulta) -> tuple[VistaCatalogo, IteradorPaginas]:
        """Primera página, total y conteos; devuelve también el iterador posicionado."""

    @abstractmethod
    def crear_iterador(self, consulta: Consulta) -> IteradorPaginas: ...

    def pagina_offset(self, consulta: Consulta, pagina: int) -> Pagina:  # pragma: no cover
        raise NotImplementedError

    def pagina_cursor(self, consulta: Consulta, cursor) -> Pagina:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------
    def detalles(self, ids: list[int]) -> list[dict]:
        """Lee los productos de una página por clave primaria, en el orden dado."""
        if not ids:
            return []
        con = self.conexiones.get()
        filas = con.execute(
            f"SELECT {', '.join(CAMPOS)} FROM productos WHERE id IN ({','.join('?' * len(ids))})",
            ids).fetchall()
        por_id = {f[0]: dict(zip(CAMPOS, f)) for f in filas}
        return [por_id[i] for i in ids if i in por_id]
