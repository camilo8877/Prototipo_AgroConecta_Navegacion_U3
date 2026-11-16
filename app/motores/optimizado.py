"""Perfil «optimizado»: modelo de lectura en memoria para navegar el catálogo.

Componentes:
* IndiceCatalogo (observador del inventario): columnas en memoria, un índice
  invertido de máscaras por valor de faceta y por nodo del árbol, y un índice
  ordenado por cada estrategia de orden. Se mantiene por eventos.
* MotorOptimizado: arma la vista con operaciones vectorizadas (AND de máscaras
  + bincount para los conteos) y pagina por cursor con la estrategia de
  recorrido que elige el planificador.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from ..catalogo_def import FACETAS, FACETAS_POR_NOMBRE
from ..patrones.composite_categorias import ArbolCategorias, CategoriaCompuesta, NodoCategoria
from ..patrones.iterator_paginacion import IteradorCursor
from ..patrones.modelos import Consulta, Pagina, VistaCatalogo
from ..patrones.observer_inventario import EventoInventario, PublicadorInventario
from ..patrones.strategy_orden import ORDENES
from ..patrones.strategy_recorrido import EstrategiaRecorrido, PlanificadorRecorrido
from .base import MotorCatalogo


class IndiceCatalogo:
    """Modelo de lectura en memoria. Es un observador del inventario."""

    def __init__(self, con, arbol: ArbolCategorias):
        t0 = time.perf_counter()
        self.arbol = arbol
        self._candado = threading.Lock()
        self.version = 0
        filas = con.execute(
            "SELECT id, categoria_id, municipio, calidad, organico, precio, dias_cosecha, "
            "distancia_km, disponible_kg FROM productos").fetchall()
        n_max = max((f[0] for f in filas), default=0)
        self.capacidad = int(n_max * 1.1) + 1024
        cap = self.capacidad
        self.cols: dict[str, np.ndarray] = {
            "categoria": np.zeros(cap, np.int16),
            "precio": np.zeros(cap, np.int32),
            "dias": np.zeros(cap, np.int16),
            "distancia_dm": np.zeros(cap, np.int32),
        }
        self.codigos: dict[str, np.ndarray] = {f.nombre: np.zeros(cap, np.int8) for f in FACETAS}
        self.existe = np.zeros(cap, bool)
        self.disponible = np.zeros(cap, bool)

        if filas:
            a = np.array([(f[0], f[1], f[5], f[6], round(f[7] * 10), f[8], f[4]) for f in filas],
                         dtype=np.int64)
            ids = a[:, 0]
            self.cols["categoria"][ids] = a[:, 1]
            self.cols["precio"][ids] = a[:, 2]
            self.cols["dias"][ids] = a[:, 3]
            self.cols["distancia_dm"][ids] = a[:, 4]
            self.disponible[ids] = a[:, 5] > 0
            self.existe[ids] = True
            for faceta in FACETAS:
                cod = np.fromiter(
                    (faceta.codificar({"municipio": f[2], "calidad": f[3], "organico": f[4],
                                       "precio": f[5], "dias_cosecha": f[6]}) for f in filas),
                    dtype=np.int8, count=len(filas))
                self.codigos[faceta.nombre][ids] = cod

        # Índice invertido: una máscara booleana por valor de faceta …
        self.mascaras_faceta: dict[str, list[np.ndarray]] = {
            f.nombre: [(self.codigos[f.nombre] == c) & self.existe for c in range(len(f.valores))]
            for f in FACETAS
        }
        # … y una por nodo del árbol (Composite: el compuesto = OR de sus hijos).
        self.mascaras_categoria: dict[int, np.ndarray] = {}
        self._construir_mascara(arbol.raiz)

        # Índices ordenados por cada estrategia de orden (clave compuesta, id).
        self.ordenes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        vivos = np.flatnonzero(self.existe)
        for nombre, estrategia in ORDENES.items():
            claves = estrategia.clave_vector(self.cols, vivos)
            perm = np.argsort(claves, kind="stable")
            self.ordenes[nombre] = (claves[perm], vivos[perm].astype(np.int64))
        self.tiempo_construccion_ms = (time.perf_counter() - t0) * 1000

    def _construir_mascara(self, nodo: NodoCategoria) -> np.ndarray:
        if isinstance(nodo, CategoriaCompuesta):
            m = np.zeros(self.capacidad, bool)
            for hijo in nodo.hijos:
                m |= self._construir_mascara(hijo)
        else:
            m = (self.cols["categoria"] == nodo.id) & self.existe
        self.mascaras_categoria[nodo.id] = m
        return m

    @property
    def n_productos(self) -> int:
        return len(self.ordenes["precio_asc"][1])

    def memoria_mb(self) -> float:
        total = sum(a.nbytes for a in self.cols.values()) + sum(a.nbytes for a in self.codigos.values())
        total += sum(m.nbytes for ms in self.mascaras_faceta.values() for m in ms)
        total += sum(m.nbytes for m in self.mascaras_categoria.values())
        total += sum(c.nbytes + i.nbytes for c, i in self.ordenes.values())
        total += self.existe.nbytes + self.disponible.nbytes
        return total / 1_048_576

    # ------------------------------------------------------------------
    # Observer: mantenimiento incremental
    # ------------------------------------------------------------------
    def actualizar(self, evento: EventoInventario) -> None:
        with self._candado:
            i = evento.producto_id
            if evento.tipo == "nuevo_lote":
                self._agregar(i, evento.datos)
            elif evento.tipo == "agotado":
                self.disponible[i] = False
            elif evento.tipo == "reabastecido":
                self.disponible[i] = evento.datos["disponible_kg"] > 0
            elif evento.tipo == "cambio_precio":
                self._cambiar_precio(i, evento.datos["precio"])
            self.version += 1

    def _asegurar_capacidad(self, i: int) -> None:
        if i < self.capacidad:
            return
        nueva = max(i + 1, int(self.capacidad * 1.5))
        extra = nueva - self.capacidad

        def crecer(a: np.ndarray) -> np.ndarray:
            return np.concatenate([a, np.zeros(extra, a.dtype)])

        self.cols = {k: crecer(v) for k, v in self.cols.items()}
        self.codigos = {k: crecer(v) for k, v in self.codigos.items()}
        self.existe, self.disponible = crecer(self.existe), crecer(self.disponible)
        self.mascaras_faceta = {k: [crecer(m) for m in ms] for k, ms in self.mascaras_faceta.items()}
        self.mascaras_categoria = {k: crecer(m) for k, m in self.mascaras_categoria.items()}
        self.capacidad = nueva

    def _insertar_orden(self, nombre: str, clave: int, i: int) -> None:
        claves, ids = self.ordenes[nombre]
        pos = int(np.searchsorted(claves, clave))
        self.ordenes[nombre] = (np.insert(claves, pos, clave), np.insert(ids, pos, i))

    def _quitar_orden(self, nombre: str, clave: int) -> None:
        claves, ids = self.ordenes[nombre]
        pos = int(np.searchsorted(claves, clave))
        if pos < len(claves) and claves[pos] == clave:
            self.ordenes[nombre] = (np.delete(claves, pos), np.delete(ids, pos))

    def _agregar(self, i: int, d: dict) -> None:
        self._asegurar_capacidad(i)
        self.cols["categoria"][i] = d["categoria_id"]
        self.cols["precio"][i] = d["precio"]
        self.cols["dias"][i] = d["dias_cosecha"]
        self.cols["distancia_dm"][i] = round(d["distancia_km"] * 10)
        for faceta in FACETAS:
            c = faceta.codificar(d)
            self.codigos[faceta.nombre][i] = c
            self.mascaras_faceta[faceta.nombre][c][i] = True
        hoja = self.arbol.nodo(d["categoria_id"])
        self.mascaras_categoria[hoja.id][i] = True
        for ancestro in hoja.ancestros():
            self.mascaras_categoria[ancestro.id][i] = True
        self.existe[i] = True
        self.disponible[i] = d["disponible_kg"] > 0
        for nombre, est in ORDENES.items():
            clave = est.clave_fila(d["precio"], d["dias_cosecha"], round(d["distancia_km"] * 10), i)
            self._insertar_orden(nombre, clave, i)

    def _cambiar_precio(self, i: int, precio: int) -> None:
        dias, dist = int(self.cols["dias"][i]), int(self.cols["distancia_dm"][i])
        anterior = int(self.cols["precio"][i])
        for nombre in ("precio_asc", "precio_desc"):
            self._quitar_orden(nombre, ORDENES[nombre].clave_fila(anterior, dias, dist, i))
        faceta = FACETAS_POR_NOMBRE["precio"]
        c_ant = int(self.codigos["precio"][i])
        c_nuevo = faceta.codificar({"precio": precio})
        self.mascaras_faceta["precio"][c_ant][i] = False
        self.mascaras_faceta["precio"][c_nuevo][i] = True
        self.codigos["precio"][i] = c_nuevo
        self.cols["precio"][i] = precio
        for nombre in ("precio_asc", "precio_desc"):
            self._insertar_orden(nombre, ORDENES[nombre].clave_fila(precio, dias, dist, i), i)


class MotorOptimizado(MotorCatalogo):
    perfil = "optimizado"

    def __init__(self, ruta_db, publicador: PublicadorInventario | None = None, **kw):
        super().__init__(ruta_db, **kw)
        self.indice = IndiceCatalogo(self.conexiones.get(), self.arbol)
        if publicador is not None:
            publicador.suscribir(self.indice)
        self.planificador = PlanificadorRecorrido()
        self.estrategia_forzada: EstrategiaRecorrido | None = None

    @property
    def version(self) -> int:
        return self.indice.version

    # --- filtros como máscaras ---------------------------------------------
    def _partes(self, consulta: Consulta) -> dict[str, np.ndarray]:
        idx = self.indice
        partes: dict[str, np.ndarray] = {}
        if consulta.categoria_id != self.arbol.raiz.id:
            partes["categoria"] = idx.mascaras_categoria[consulta.categoria_id]
        for nombre, codigos in consulta.filtros:
            ms = idx.mascaras_faceta[nombre]
            m = ms[codigos[0]]
            for c in codigos[1:]:
                m = m | ms[c]
            partes[nombre] = m
        return partes

    def _combinar(self, partes: dict[str, np.ndarray], excluir: str | None = None) -> np.ndarray:
        resultado = self.indice.disponible.copy()
        for nombre, m in partes.items():
            if nombre != excluir:
                np.logical_and(resultado, m[: len(resultado)], out=resultado)
        return resultado

    def filtro(self, consulta: Consulta) -> np.ndarray:
        return self._combinar(self._partes(consulta))

    # --- API del motor -----------------------------------------------------------
    def vista(self, consulta: Consulta):
        t0 = time.perf_counter()
        idx = self.indice
        partes = self._partes(consulta)
        filtro = self._combinar(partes)
        total = int(np.count_nonzero(filtro))
        t1 = time.perf_counter()

        conteo_facetas: dict[str, list[int]] = {}
        for faceta in FACETAS:
            g = filtro if faceta.nombre not in partes else self._combinar(partes, faceta.nombre)
            cods = idx.codigos[faceta.nombre][: len(g)][g]
            conteo_facetas[faceta.nombre] = np.bincount(cods, minlength=len(faceta.valores)).tolist()
        g = filtro if "categoria" not in partes else self._combinar(partes, "categoria")
        bc = np.bincount(idx.cols["categoria"][: len(g)][g], minlength=self.arbol.max_id + 1)
        conteo_hojas = {int(h): int(bc[h]) for h in np.flatnonzero(bc)}
        t2 = time.perf_counter()

        primera = self._pagina_con_filtro(consulta, None, filtro, total)
        iterador = IteradorCursor(self, consulta, cursor=primera.cursor)
        iterador.terminado = not primera.hay_mas
        t3 = time.perf_counter()
        vista = VistaCatalogo(
            consulta=consulta, productos=primera.productos, total=total,
            conteo_facetas=conteo_facetas, conteo_hojas=conteo_hojas, hay_mas=primera.hay_mas,
            tiempo_ms=(t3 - t0) * 1000, estrategia=f"Índice en memoria + {primera.estrategia}",
            consultas_sql=1,
            detalle_ms={"total": (t1 - t0) * 1000, "facetas": (t2 - t1) * 1000, "pagina": (t3 - t2) * 1000},
            version=self.version,
        )
        return vista, iterador

    def crear_iterador(self, consulta: Consulta) -> IteradorCursor:
        return IteradorCursor(self, consulta)

    def pagina_cursor(self, consulta: Consulta, cursor) -> Pagina:
        filtro = self.filtro(consulta)
        return self._pagina_con_filtro(consulta, cursor, filtro, int(np.count_nonzero(filtro)))

    def _pagina_con_filtro(self, consulta: Consulta, cursor, filtro: np.ndarray, m: int) -> Pagina:
        t0 = time.perf_counter()
        orden = ORDENES[consulta.orden]
        claves, ids = self.indice.ordenes[consulta.orden]
        cols = self.indice.cols
        clave_de = lambda arr: orden.clave_vector(cols, arr)  # noqa: E731
        if self.estrategia_forzada is not None:
            nombre = self.estrategia_forzada.nombre
            ids_pag, ultima, hay_mas = self.estrategia_forzada.pagina(
                filtro, claves, ids, clave_de, cursor, self.tam)
        else:
            (ids_pag, ultima, hay_mas), nombre = self.planificador.ejecutar(
                filtro, claves, ids, clave_de, cursor, self.tam, m)
        productos = self.detalles(ids_pag)
        return Pagina(productos, hay_mas, (time.perf_counter() - t0) * 1000, nombre,
                      cursor=ultima if ultima is not None else cursor, consultas_sql=1)
