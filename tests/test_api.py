"""Prueba de punta a punta de la API con un catálogo pequeño."""
import importlib
import os


def test_flujo_api(monkeypatch):
    monkeypatch.setenv("CATALOGO_N", "3000")
    import app.main as main
    main = importlib.reload(main)
    from fastapi.testclient import TestClient

    cliente = TestClient(main.app)
    assert cliente.get("/").status_code == 200
    for perfil in ("base", "optimizado"):
        r = cliente.post("/api/sesiones", json={"perfil": perfil}).json()
        sid = r["sesion_id"]
        assert r["total"] > 0 and len(r["productos"]) == 24
        r = cliente.post(f"/api/sesiones/{sid}/comandos", json={"tipo": "categoria", "categoria_id": 2}).json()
        assert [n["nombre"] for n in r["ruta"]] == ["Catálogo", "Frutas"]
        r = cliente.post(f"/api/sesiones/{sid}/comandos", json={"tipo": "filtro", "faceta": "organico", "codigo": 1}).json()
        assert r["consulta"]["filtros"] == {"organico": [1]}
        r = cliente.post(f"/api/sesiones/{sid}/deshacer").json()
        assert r["consulta"]["filtros"] == {}
        r = cliente.post(f"/api/sesiones/{sid}/rehacer").json()
        assert r["historial"]["deshacer"][-1].startswith("Producción")
    r = cliente.get("/api/catalogo", params={"perfil": "optimizado", "f": "municipio:0,1"}).json()
    assert "servidor_ms" in r and r["total"] > 0
    r = cliente.post("/api/inventario/simular", json={"tipo": "nuevo_lote", "cantidad": 5}).json()
    assert r["version_indice"] >= 5
    assert cliente.get("/api/metricas").status_code == 200
    os.environ.pop("CATALOGO_N", None)
