"""Pruebas unitarias de cada patrón de diseño."""
import numpy as np

from app.datos import fila_aleatoria, hojas_desde_db
from app.patrones.command_navegacion import (AlternarFiltro, CambiarOrden, CargarMas,
                                             SeleccionarCategoria, SesionNavegacion)
from app.patrones.composite_categorias import CategoriaCompuesta
from app.patrones.modelos import Consulta
from app.patrones.strategy_recorrido import ExtraccionDirecta, RecorridoOrdenado


# --- Composite -------------------------------------------------------------
def test_composite_conteo_y_ruta(sistema):
    base, opt, _ = sistema
    v, _ = opt.vista(Consulta())
    raiz = opt.arbol.raiz
    assert raiz.contar(v.conteo_hojas) == v.total
    for hijo in raiz.hijos:
        assert isinstance(hijo, CategoriaCompuesta)
        assert hijo.contar(v.conteo_hojas) == sum(h.contar(v.conteo_hojas) for h in hijo.hijos)
    mora = next(h for h in raiz.hojas() if h.nombre == "Mora de Castilla")
    assert [n.nombre for n in mora.ruta()] == ["Catálogo", "Frutas", "Bayas", "Mora de Castilla"]


def test_composite_mascara_es_union_de_hijos(sistema):
    _, opt, _ = sistema
    idx = opt.indice
    for nodo in opt.arbol.por_id.values():
        if isinstance(nodo, CategoriaCompuesta):
            union = np.zeros_like(idx.existe)
            for h in nodo.hijos:
                union |= idx.mascaras_categoria[h.id]
            assert np.array_equal(union, idx.mascaras_categoria[nodo.id])


# --- Strategy (recorrido) -------------------------------------------------
def test_estrategias_de_recorrido_equivalentes(sistema, rng):
    _, opt, _ = sistema
    consultas = [Consulta(), Consulta(categoria_id=8, filtros=(("organico", (1,)),)),
                 Consulta(filtros=(("municipio", (14,)), ("calidad", (2,))), orden="frescura")]
    for c in consultas:
        resultados = []
        for est in (RecorridoOrdenado(), ExtraccionDirecta()):
            opt.estrategia_forzada = est
            resultados.append([p["id"] for pag in opt.crear_iterador(c) for p in pag.productos])
        opt.estrategia_forzada = None
        assert resultados[0] == resultados[1]


def test_planificador_elige_segun_selectividad(sistema):
    _, opt, _ = sistema
    plan = opt.planificador
    assert plan.elegir(m=200_000, n_total=200_000, tam=24).nombre == "recorrido ordenado"
    assert plan.elegir(m=30, n_total=200_000, tam=24).nombre == "extracción directa"


# --- Iterator ----------------------------------------------------------------------
def test_iteradores_cubren_todo_sin_repetir(sistema):
    base, opt, _ = sistema
    c = Consulta(categoria_id=2)
    total = base.vista(c)[0].total
    for motor in (base, opt):
        ids = [p["id"] for pag in motor.crear_iterador(c) for p in pag.productos]
        assert len(ids) == len(set(ids)) == total


def test_cursor_estable_con_inserciones_y_offset_no(sistema, rng, ruta_db):
    base, opt, pub = sistema
    hojas = hojas_desde_db(base.conexiones.get())
    c = Consulta(orden="precio_asc")
    it_b, it_o = base.crear_iterador(c), opt.crear_iterador(c)
    vistos_b, vistos_o = [], []
    for _ in range(6):
        vistos_b += [p["id"] for p in next(it_b).productos]
        vistos_o += [p["id"] for p in next(it_o).productos]
        for _ in range(5):  # llegan lotes baratos que quedan antes de la posición actual
            fila = list(fila_aleatoria(rng, hojas))
            fila[4], fila[9] = 100, 50
            pub.registrar_lote(tuple(fila))
    assert len(vistos_o) == len(set(vistos_o))          # el cursor nunca repite
    assert len(vistos_b) > len(set(vistos_b))           # OFFSET repite productos


# --- Observer -------------------------------------------------------------------------
def test_observer_mantiene_indice_sincronizado(sistema, rng):
    base, opt, pub = sistema
    hojas = hojas_desde_db(base.conexiones.get())
    v0 = opt.version
    for _ in range(20):
        pub.registrar_lote(fila_aleatoria(rng, hojas))
    for i in rng.sample(range(1, 5000), 30):
        pub.agotar(i)
    for i in rng.sample(range(1, 5000), 30):
        pub.cambiar_precio(i, rng.randint(10, 300) * 50)
    assert opt.version == v0 + 80
    for c in (Consulta(), Consulta(categoria_id=19, orden="precio_desc", filtros=(("precio", (1, 2)),))):
        vb, _ = base.vista(c)
        vo, _ = opt.vista(c)
        assert (vb.total, vb.conteo_facetas, vb.conteo_hojas) == (vo.total, vo.conteo_facetas, vo.conteo_hojas)
        assert [p["id"] for p in vb.productos] == [p["id"] for p in vo.productos]


# --- Command ----------------------------------------------------------------------------
def test_comandos_deshacer_y_rehacer(sistema):
    _, opt, _ = sistema
    s = SesionNavegacion(opt)
    inicial = s.consulta
    s.ejecutar(SeleccionarCategoria(2))
    s.ejecutar(AlternarFiltro("organico", 1))
    s.ejecutar(CambiarOrden("frescura"))
    s.ejecutar(CargarMas())
    assert len(s.productos) == min(48, s.vista.total)
    despues = s.consulta
    for _ in range(4):
        assert s.deshacer()
    assert s.consulta == inicial and len(s.productos) == 24
    assert s.ultima_operacion["estrategia"] == "memento (sin consultar)"
    for _ in range(4):
        assert s.rehacer()
    assert s.consulta == despues


def test_memento_se_invalida_si_cambia_el_inventario(sistema, rng):
    base, opt, pub = sistema
    s = SesionNavegacion(opt)
    s.ejecutar(SeleccionarCategoria(2))
    pub.agotar(s.productos[0]["id"])
    s.ejecutar(AlternarFiltro("calidad", 0))
    s.deshacer()
    assert s.ultima_operacion["estrategia"] == "memento (sin consultar)"  # misma versión
    pub.agotar(s.productos[0]["id"])
    s.deshacer()
    assert s.ultima_operacion["estrategia"] == "nueva consulta"           # versión distinta
