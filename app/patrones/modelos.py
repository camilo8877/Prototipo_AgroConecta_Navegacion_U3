"""Objetos de valor que viajan entre la navegación y los motores."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Consulta:
    """Estado inmutable de navegación: categoría + filtros + orden."""

    categoria_id: int = 1
    filtros: tuple[tuple[str, tuple[int, ...]], ...] = ()
    orden: str = "precio_asc"

    def filtros_dict(self) -> dict[str, tuple[int, ...]]:
        return dict(self.filtros)

    def con_categoria(self, categoria_id: int) -> "Consulta":
        return replace(self, categoria_id=categoria_id)

    def con_orden(self, orden: str) -> "Consulta":
        return replace(self, orden=orden)

    def alternar_filtro(self, faceta: str, codigo: int) -> "Consulta":
        filtros = self.filtros_dict()
        actuales = set(filtros.get(faceta, ()))
        actuales ^= {codigo}
        if actuales:
            filtros[faceta] = tuple(sorted(actuales))
        else:
            filtros.pop(faceta, None)
        return replace(self, filtros=tuple(sorted(filtros.items())))

    def sin_filtros(self) -> "Consulta":
        return replace(self, filtros=())


@dataclass
class Pagina:
    productos: list[dict]
    hay_mas: bool
    tiempo_ms: float
    estrategia: str
    cursor: object = None
    consultas_sql: int = 0


@dataclass
class VistaCatalogo:
    """Primera página + conteos de facetas y del árbol para una consulta."""

    consulta: Consulta
    productos: list[dict]
    total: int
    conteo_facetas: dict[str, list[int]]
    conteo_hojas: dict[int, int]
    hay_mas: bool
    tiempo_ms: float
    estrategia: str
    consultas_sql: int = 0
    detalle_ms: dict[str, float] = field(default_factory=dict)
    version: int = 0
