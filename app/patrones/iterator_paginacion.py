"""Patrón Iterator: recorrido página a página del catálogo.

El cliente (la sesión de navegación) recorre las páginas con `next()` sin saber
si debajo hay un OFFSET de SQL o un cursor sobre un índice ordenado. Ambos
iteradores exponen su estado para que el Command pueda guardarlo y restaurarlo.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .modelos import Consulta, Pagina

if TYPE_CHECKING:  # pragma: no cover
    from ..motores.base import MotorCatalogo


class IteradorPaginas(ABC):
    def __init__(self, motor: "MotorCatalogo", consulta: Consulta):
        self.motor = motor
        self.consulta = consulta
        self.terminado = False

    def __iter__(self) -> "IteradorPaginas":
        return self

    def __next__(self) -> Pagina:
        if self.terminado:
            raise StopIteration
        pagina = self._siguiente()
        if not pagina.hay_mas:
            self.terminado = True
        if not pagina.productos:
            raise StopIteration
        return pagina

    @abstractmethod
    def _siguiente(self) -> Pagina: ...

    @abstractmethod
    def estado(self) -> object: ...

    @abstractmethod
    def restaurar(self, estado: object) -> None: ...


class IteradorOffset(IteradorPaginas):
    """Línea base: página n → LIMIT tam OFFSET n·tam (la base de datos descarta n·tam filas)."""

    def __init__(self, motor, consulta, pagina: int = 0):
        super().__init__(motor, consulta)
        self.pagina = pagina

    def _siguiente(self) -> Pagina:
        p = self.motor.pagina_offset(self.consulta, self.pagina)
        self.pagina += 1
        return p

    def estado(self):
        return (self.pagina, self.terminado)

    def restaurar(self, estado) -> None:
        self.pagina, self.terminado = estado


class IteradorCursor(IteradorPaginas):
    """Optimizado: «dame lo que sigue después de la clave X» (keyset)."""

    def __init__(self, motor, consulta, cursor: int | None = None):
        super().__init__(motor, consulta)
        self.cursor = cursor

    def _siguiente(self) -> Pagina:
        p = self.motor.pagina_cursor(self.consulta, self.cursor)
        self.cursor = p.cursor
        return p

    def estado(self):
        return (self.cursor, self.terminado)

    def restaurar(self, estado) -> None:
        self.cursor, self.terminado = estado
