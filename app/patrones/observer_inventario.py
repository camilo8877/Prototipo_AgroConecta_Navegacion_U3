"""Patrón Observer: cambios de inventario que mantienen al día el índice.

El publicador escribe primero en la base de datos (fuente de verdad) y luego
notifica a sus observadores. El índice de navegación se actualiza de forma
incremental (un bit, una posición), en lugar de reconstruirse o de recalcular
los conteos en cada petición.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class EventoInventario:
    tipo: str                      # nuevo_lote | agotado | reabastecido | cambio_precio
    producto_id: int
    datos: dict = field(default_factory=dict)


class ObservadorInventario(Protocol):
    def actualizar(self, evento: EventoInventario) -> None: ...


COLUMNAS = ("nombre", "categoria_id", "municipio", "finca", "precio", "organico",
            "calidad", "dias_cosecha", "distancia_km", "disponible_kg")


class PublicadorInventario:
    """Sujeto del Observer."""

    def __init__(self, ruta_db: Path):
        self._con = sqlite3.connect(ruta_db, check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._observadores: list[ObservadorInventario] = []
        self._candado = threading.Lock()
        self.eventos_publicados = 0

    def suscribir(self, observador: ObservadorInventario) -> None:
        self._observadores.append(observador)

    def desuscribir(self, observador: ObservadorInventario) -> None:
        self._observadores.remove(observador)

    def _notificar(self, evento: EventoInventario) -> None:
        for obs in list(self._observadores):
            obs.actualizar(evento)
        self.eventos_publicados += 1

    # --- operaciones de negocio ------------------------------------------
    def registrar_lote(self, fila: tuple) -> int:
        with self._candado:
            cur = self._con.execute(
                f"INSERT INTO productos({', '.join(COLUMNAS)}) VALUES ({', '.join('?' * len(COLUMNAS))})",
                fila)
            self._con.commit()
            id_ = int(cur.lastrowid)
            self._notificar(EventoInventario("nuevo_lote", id_, dict(zip(COLUMNAS, fila))))
            return id_

    def agotar(self, producto_id: int) -> None:
        with self._candado:
            self._con.execute("UPDATE productos SET disponible_kg = 0 WHERE id = ?", (producto_id,))
            self._con.commit()
            self._notificar(EventoInventario("agotado", producto_id))

    def reabastecer(self, producto_id: int, kg: int) -> None:
        with self._candado:
            self._con.execute("UPDATE productos SET disponible_kg = ? WHERE id = ?", (kg, producto_id))
            self._con.commit()
            self._notificar(EventoInventario("reabastecido", producto_id, {"disponible_kg": kg}))

    def cambiar_precio(self, producto_id: int, precio: int) -> None:
        with self._candado:
            self._con.execute("UPDATE productos SET precio = ? WHERE id = ?", (precio, producto_id))
            self._con.commit()
            self._notificar(EventoInventario("cambio_precio", producto_id, {"precio": precio}))

    def cerrar(self) -> None:
        self._con.close()
