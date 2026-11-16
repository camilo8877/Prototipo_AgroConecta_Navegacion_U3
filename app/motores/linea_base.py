"""Perfil «línea base»: navegación resuelta en cada petición con SQL directo.

Así funcionaba el catálogo de las unidades anteriores: cada vez que el
comprador hace clic se ejecuta un COUNT(*), un GROUP BY por cada faceta y la
página se pide con LIMIT/OFFSET. Es correcto, simple y sin estado, pero su
costo crece con el tamaño del catálogo y con la profundidad de la página.
"""
from __future__ import annotations

import time

from ..catalogo_def import FACETAS
from ..patrones.iterator_paginacion import IteradorOffset
from ..patrones.modelos import Consulta, Pagina, VistaCatalogo
from ..patrones.strategy_orden import ORDENES
from .base import CAMPOS, MotorCatalogo


class MotorLineaBase(MotorCatalogo):
    perfil = "base"

    def _where(self, consulta: Consulta, excluir: str | None = None) -> tuple[str, list]:
        condiciones, params = ["disponible_kg > 0"], []
        if excluir != "categoria" and consulta.categoria_id != self.arbol.raiz.id:
            hojas = [h.id for h in self.arbol.nodo(consulta.categoria_id).hojas()]
            condiciones.append(f"categoria_id IN ({','.join('?' * len(hojas))})")
            params += hojas
        for faceta in FACETAS:
            codigos = consulta.filtros_dict().get(faceta.nombre)
            if not codigos or faceta.nombre == excluir:
                continue
            partes = []
            for c in codigos:
                pred, p = faceta.predicados_sql[c]
                partes.append(pred)
                params += list(p)
            condiciones.append("(" + " OR ".join(partes) + ")")
        return " AND ".join(condiciones), params

    def vista(self, consulta: Consulta):
        t0 = time.perf_counter()
        con = self.conexiones.get()
        detalle = {}
        where, params = self._where(consulta)
        total = con.execute(f"SELECT COUNT(*) FROM productos WHERE {where}", params).fetchone()[0]
        t1 = time.perf_counter()
        detalle["total"] = (t1 - t0) * 1000

        conteo_facetas: dict[str, list[int]] = {}
        for faceta in FACETAS:
            w, p = self._where(consulta, excluir=faceta.nombre)
            filas = con.execute(
                f"SELECT {faceta.expr_sql} AS v, COUNT(*) FROM productos WHERE {w} GROUP BY v", p
            ).fetchall()
            conteos = [0] * len(faceta.valores)
            for v, n in filas:
                conteos[int(v)] = n
            conteo_facetas[faceta.nombre] = conteos
        w, p = self._where(consulta, excluir="categoria")
        conteo_hojas = dict(con.execute(
            f"SELECT categoria_id, COUNT(*) FROM productos WHERE {w} GROUP BY categoria_id", p
        ).fetchall())
        t2 = time.perf_counter()
        detalle["facetas"] = (t2 - t1) * 1000

        iterador = self.crear_iterador(consulta)
        primera = next(iterador, None)
        t3 = time.perf_counter()
        detalle["pagina"] = (t3 - t2) * 1000
        vista = VistaCatalogo(
            consulta=consulta,
            productos=primera.productos if primera else [],
            total=total,
            conteo_facetas=conteo_facetas,
            conteo_hojas=conteo_hojas,
            hay_mas=bool(primera and primera.hay_mas),
            tiempo_ms=(t3 - t0) * 1000,
            estrategia="SQL: COUNT + GROUP BY por faceta + LIMIT/OFFSET",
            consultas_sql=len(FACETAS) + 3,
            detalle_ms=detalle,
        )
        return vista, iterador

    def crear_iterador(self, consulta: Consulta) -> IteradorOffset:
        return IteradorOffset(self, consulta)

    def pagina_offset(self, consulta: Consulta, pagina: int) -> Pagina:
        t0 = time.perf_counter()
        where, params = self._where(consulta)
        orden = ORDENES[consulta.orden]
        filas = self.conexiones.get().execute(
            f"SELECT {', '.join(CAMPOS)} FROM productos WHERE {where} ORDER BY {orden.sql} "
            f"LIMIT ? OFFSET ?", params + [self.tam + 1, pagina * self.tam]
        ).fetchall()
        productos = [dict(zip(CAMPOS, f)) for f in filas[: self.tam]]
        return Pagina(productos, len(filas) > self.tam, (time.perf_counter() - t0) * 1000,
                      "LIMIT/OFFSET", cursor=pagina + 1, consultas_sql=1)
