import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.datos import generar_catalogo  # noqa: E402
from app.motores.linea_base import MotorLineaBase  # noqa: E402
from app.motores.optimizado import MotorOptimizado  # noqa: E402
from app.patrones.observer_inventario import PublicadorInventario  # noqa: E402


@pytest.fixture()
def ruta_db(tmp_path):
    return generar_catalogo(5000, tmp_path / "catalogo_test.db", semilla=11)


@pytest.fixture()
def sistema(ruta_db):
    publicador = PublicadorInventario(ruta_db)
    base = MotorLineaBase(ruta_db)
    opt = MotorOptimizado(ruta_db, publicador)
    yield base, opt, publicador
    publicador.cerrar()


@pytest.fixture()
def rng():
    return random.Random(2026)
