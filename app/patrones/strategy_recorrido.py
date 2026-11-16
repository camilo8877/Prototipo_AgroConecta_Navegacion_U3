"""Patrón Strategy: cómo recorrer el catálogo filtrado para armar una página.

Dos estrategias intercambiables producen exactamente el mismo resultado con
costos opuestos:

* RecorridoOrdenado: camina por el índice ya ordenado desde el cursor y se
  detiene al reunir una página. Barato cuando el filtro deja pasar muchos
  productos (pocos pasos), caro cuando es muy selectivo.
* ExtraccionDirecta: extrae los candidatos que cumplen el filtro, los ordena y
  toma la página. Barato cuando quedan pocos candidatos.

El PlanificadorRecorrido elige en cada petición con un modelo de costo simple
basado en la selectividad (m productos que cumplen de N), al estilo de un
optimizador de consultas.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Callable

import numpy as np

ResultadoRecorrido = tuple[list[int], "int | None", bool]


class EstrategiaRecorrido(ABC):
    nombre: str

    @abstractmethod
    def pagina(self, filtro: np.ndarray, claves: np.ndarray, ids: np.ndarray,
               clave_de: Callable[[np.ndarray], np.ndarray], cursor: int | None,
               tam: int) -> ResultadoRecorrido:
        """Devuelve (ids de la página, clave del último, hay_más)."""


class RecorridoOrdenado(EstrategiaRecorrido):
    nombre = "recorrido ordenado"

    def pagina(self, filtro, claves, ids, clave_de, cursor, tam):
        inicio = 0 if cursor is None else int(np.searchsorted(claves, cursor, side="right"))
        total = len(ids)
        bloque = 1024
        encontrados: list[np.ndarray] = []
        n_encontrados = 0
        pos = inicio
        while pos < total and n_encontrados <= tam:
            trozo = ids[pos:pos + bloque]
            sel = trozo[filtro[trozo]]
            if len(sel):
                encontrados.append(sel)
                n_encontrados += len(sel)
            pos += bloque
            bloque = min(bloque * 2, 65536)   # crece si el filtro es selectivo
        if not encontrados:
            return [], None, False
        todos = np.concatenate(encontrados)
        pagina = todos[:tam]
        hay_mas = len(todos) > tam
        ultima = int(clave_de(pagina[-1:])[0])
        return pagina.tolist(), ultima, hay_mas


class ExtraccionDirecta(EstrategiaRecorrido):
    nombre = "extracción directa"

    def pagina(self, filtro, claves, ids, clave_de, cursor, tam):
        candidatos = np.flatnonzero(filtro)
        if len(candidatos) == 0:
            return [], None, False
        k = clave_de(candidatos)
        if cursor is not None:
            vivos = k > cursor
            candidatos, k = candidatos[vivos], k[vivos]
        if len(k) == 0:
            return [], None, False
        n = min(tam + 1, len(k))
        if n < len(k):
            sel = np.argpartition(k, n - 1)[:n]
        else:
            sel = np.arange(len(k))
        sel = sel[np.argsort(k[sel], kind="stable")]
        hay_mas = len(sel) > tam
        sel = sel[:tam]
        return candidatos[sel].tolist(), int(k[sel[-1]]), hay_mas


class PlanificadorRecorrido:
    """Elige la estrategia de menor costo estimado.

    costo(recorrido)  ≈ C_REC · (tam + 1) · N / m      (elementos que hay que revisar)
    costo(extracción) ≈ C_SCAN · N + C_ORD · m · log2(m)
    Las constantes se calibraron con el escenario E3 de scripts/benchmark.py
    (punto de cruce medido cerca de 0,2 % de selectividad con 200.000 productos).
    """

    C_REC = 6.0
    C_SCAN = 0.35
    C_ORD = 3.0

    def __init__(self) -> None:
        self.recorrido = RecorridoOrdenado()
        self.extraccion = ExtraccionDirecta()

    def costos(self, m: int, n_total: int, tam: int) -> tuple[float, float]:
        if m <= 0:
            return 0.0, 0.0
        c_rec = self.C_REC * (tam + 1) * n_total / m
        c_ext = self.C_SCAN * n_total + self.C_ORD * m * math.log2(max(m, 2))
        return c_rec, c_ext

    def elegir(self, m: int, n_total: int, tam: int) -> EstrategiaRecorrido:
        c_rec, c_ext = self.costos(m, n_total, tam)
        return self.recorrido if c_rec <= c_ext else self.extraccion

    def ejecutar(self, filtro, claves, ids, clave_de, cursor, tam, m: int):
        """Elige y ejecuta. Devuelve ((ids, última clave, hay_más), nombre de la estrategia).

        Nota de diseño: se probó un «presupuesto» que cambiaba a extracción si el
        recorrido revisaba demasiados elementos (filtros correlacionados con el
        orden). Se descartó porque, con bloques que crecen de forma geométrica, el
        peor caso del recorrido (revisar todo el índice) cuesta ~0,2 ms con 200.000
        productos, menos que la sobrecarga de cambiar de estrategia.
        """
        estrategia = self.elegir(m, len(ids), tam)
        return estrategia.pagina(filtro, claves, ids, clave_de, cursor, tam), estrategia.nombre
