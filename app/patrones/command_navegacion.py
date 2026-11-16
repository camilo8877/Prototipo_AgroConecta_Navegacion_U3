"""Patrón Command: cada acción del comprador es un objeto.

Seleccionar una categoría, marcar un filtro, cambiar el orden o cargar más
resultados se encapsulan como comandos que la sesión (invocador) ejecuta y
guarda en un historial. Así se obtienen «atrás / adelante» y migas de pan sin
que la interfaz conozca los detalles de cada acción.

Cada comando guarda un memento del estado anterior (consulta, productos
mostrados, estado del iterador y versión del índice). En el perfil optimizado,
si el inventario no cambió desde entonces (misma versión), deshacer restaura la
vista al instante; si cambió, o en la línea base, se vuelve a consultar.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..catalogo_def import FACETAS_POR_NOMBRE
from ..patrones.strategy_orden import ORDENES
from .modelos import Consulta, VistaCatalogo

if TYPE_CHECKING:  # pragma: no cover
    from ..motores.base import MotorCatalogo
    from .iterator_paginacion import IteradorPaginas


@dataclass
class Memento:
    consulta: Consulta
    vista: VistaCatalogo | None
    productos: list[dict]
    estado_iterador: object
    paginas_cargadas: int
    version: int


class SesionNavegacion:
    """Invocador y receptor: mantiene el estado de navegación de un comprador."""

    def __init__(self, motor: "MotorCatalogo", usar_memento: bool | None = None):
        self.motor = motor
        self.usar_memento = motor.perfil == "optimizado" if usar_memento is None else usar_memento
        self.consulta = Consulta(categoria_id=motor.arbol.raiz.id)
        self.vista: VistaCatalogo | None = None
        self.iterador: "IteradorPaginas | None" = None
        self.productos: list[dict] = []
        self.paginas_cargadas = 0
        self.deshechos: list[Comando] = []
        self.rehechos: list[Comando] = []
        self.ultima_operacion = {"tipo": "inicio", "tiempo_ms": 0.0, "estrategia": ""}
        self.refrescar()

    # --- operaciones del receptor -------------------------------------------
    def refrescar(self, paginas: int = 1) -> None:
        t0 = time.perf_counter()
        self.vista, self.iterador = self.motor.vista(self.consulta)
        self.productos = list(self.vista.productos)
        self.paginas_cargadas = 1
        estrategia = self.vista.estrategia
        while self.paginas_cargadas < paginas and self.vista.hay_mas:
            if not self._cargar_mas():
                break
        self.ultima_operacion = {"tipo": "consulta", "tiempo_ms": (time.perf_counter() - t0) * 1000,
                                 "estrategia": estrategia}

    def _cargar_mas(self) -> bool:
        if self.iterador is None or self.iterador.terminado:
            return False
        pagina = next(self.iterador, None)
        if pagina is None:
            return False
        self.productos.extend(pagina.productos)
        self.paginas_cargadas += 1
        self.ultima_operacion = {"tipo": "pagina", "tiempo_ms": pagina.tiempo_ms,
                                 "estrategia": pagina.estrategia}
        return True

    def hay_mas(self) -> bool:
        return self.iterador is not None and not self.iterador.terminado

    def guardar(self) -> Memento:
        return Memento(self.consulta, self.vista, list(self.productos),
                       self.iterador.estado() if self.iterador else None,
                       self.paginas_cargadas, self.motor.version)

    def restaurar(self, m: Memento) -> None:
        t0 = time.perf_counter()
        self.consulta = m.consulta
        if self.usar_memento and m.version == self.motor.version and m.vista is not None:
            self.vista = m.vista
            self.productos = list(m.productos)
            self.iterador = self.motor.crear_iterador(m.consulta)
            self.iterador.restaurar(m.estado_iterador)
            self.paginas_cargadas = m.paginas_cargadas
            modo = "memento (sin consultar)"
        else:
            self.refrescar(paginas=m.paginas_cargadas)
            modo = "nueva consulta"
        self.ultima_operacion = {"tipo": "deshacer", "tiempo_ms": (time.perf_counter() - t0) * 1000,
                                 "estrategia": modo}

    # --- invocador -----------------------------------------------------------------
    def ejecutar(self, comando: "Comando") -> None:
        comando.ejecutar(self)
        self.deshechos.append(comando)
        self.rehechos.clear()

    def deshacer(self) -> bool:
        if not self.deshechos:
            return False
        comando = self.deshechos.pop()
        comando.deshacer(self)
        self.rehechos.append(comando)
        return True

    def rehacer(self) -> bool:
        if not self.rehechos:
            return False
        comando = self.rehechos.pop()
        comando.ejecutar(self)
        self.deshechos.append(comando)
        return True


class Comando(ABC):
    def __init__(self) -> None:
        self._memento: Memento | None = None

    @property
    @abstractmethod
    def etiqueta(self) -> str: ...

    def ejecutar(self, sesion: SesionNavegacion) -> None:
        self._memento = sesion.guardar()
        self.aplicar(sesion)

    @abstractmethod
    def aplicar(self, sesion: SesionNavegacion) -> None: ...

    def deshacer(self, sesion: SesionNavegacion) -> None:
        assert self._memento is not None
        sesion.restaurar(self._memento)


class SeleccionarCategoria(Comando):
    def __init__(self, categoria_id: int):
        super().__init__()
        self.categoria_id = categoria_id
        self._nombre = ""

    @property
    def etiqueta(self) -> str:
        return f"Categoría: {self._nombre or self.categoria_id}"

    def aplicar(self, sesion):
        self._nombre = sesion.motor.arbol.nodo(self.categoria_id).nombre
        sesion.consulta = sesion.consulta.con_categoria(self.categoria_id)
        sesion.refrescar()


class AlternarFiltro(Comando):
    def __init__(self, faceta: str, codigo: int):
        super().__init__()
        self.faceta, self.codigo = faceta, codigo

    @property
    def etiqueta(self) -> str:
        f = FACETAS_POR_NOMBRE[self.faceta]
        return f"{f.etiqueta}: {f.valores[self.codigo]}"

    def aplicar(self, sesion):
        sesion.consulta = sesion.consulta.alternar_filtro(self.faceta, self.codigo)
        sesion.refrescar()


class LimpiarFiltros(Comando):
    etiqueta = "Limpiar filtros"  # type: ignore[assignment]

    def aplicar(self, sesion):
        sesion.consulta = replace(sesion.consulta.sin_filtros(), categoria_id=sesion.motor.arbol.raiz.id)
        sesion.refrescar()


class CambiarOrden(Comando):
    def __init__(self, orden: str):
        super().__init__()
        self.orden = orden

    @property
    def etiqueta(self) -> str:
        return f"Orden: {ORDENES[self.orden].etiqueta}"

    def aplicar(self, sesion):
        sesion.consulta = sesion.consulta.con_orden(self.orden)
        sesion.refrescar()


class CargarMas(Comando):
    etiqueta = "Cargar más resultados"  # type: ignore[assignment]

    def aplicar(self, sesion):
        sesion._cargar_mas()


def comando_desde_json(datos: dict) -> Comando:
    """Fábrica usada por la API para traducir la petición en un comando."""
    tipo = datos.get("tipo")
    if tipo == "categoria":
        return SeleccionarCategoria(int(datos["categoria_id"]))
    if tipo == "filtro":
        return AlternarFiltro(str(datos["faceta"]), int(datos["codigo"]))
    if tipo == "limpiar":
        return LimpiarFiltros()
    if tipo == "orden":
        return CambiarOrden(str(datos["orden"]))
    if tipo == "mas":
        return CargarMas()
    raise ValueError(f"Comando desconocido: {tipo}")
