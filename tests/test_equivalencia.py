"""La optimización no puede cambiar lo que ve el comprador: ambos perfiles deben coincidir."""
from app.catalogo_def import FACETAS
from app.patrones.modelos import Consulta
from app.patrones.strategy_orden import ORDENES


def consulta_aleatoria(rng, arbol):
    filtros = {}
    for f in rng.sample(FACETAS, rng.randint(0, 3)):
        filtros[f.nombre] = tuple(sorted(rng.sample(range(len(f.valores)), rng.randint(1, 2))))
    return Consulta(categoria_id=rng.choice(list(arbol.por_id)),
                    filtros=tuple(sorted(filtros.items())), orden=rng.choice(list(ORDENES)))


def test_vista_identica_en_100_consultas(sistema, rng):
    base, opt, _ = sistema
    for _ in range(100):
        c = consulta_aleatoria(rng, base.arbol)
        vb, _ = base.vista(c)
        vo, _ = opt.vista(c)
        assert vb.total == vo.total
        assert vb.conteo_facetas == vo.conteo_facetas
        assert vb.conteo_hojas == vo.conteo_hojas
        assert [p["id"] for p in vb.productos] == [p["id"] for p in vo.productos]


def test_recorrido_completo_identico(sistema, rng):
    base, opt, _ = sistema
    for _ in range(8):
        c = consulta_aleatoria(rng, base.arbol)
        ids_b = [p["id"] for pag in base.crear_iterador(c) for p in pag.productos]
        ids_o = [p["id"] for pag in opt.crear_iterador(c) for p in pag.productos]
        assert ids_b == ids_o
        assert len(ids_o) == len(set(ids_o)) == base.vista(c)[0].total
