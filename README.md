# AgroConecta · Navegación eficiente del catálogo (Unidad 3)

Prototipo del curso **Arquitectura de Software**, actividad *Navegando mareas: estrategias de navegación en la arquitectura de software*.

**Problema:** un restaurante del Valle de Aburrá que busca, por ejemplo, *mora orgánica cosechada ayer en el Oriente Antioqueño* debe recorrer un catálogo de decenas de miles de lotes. Con la arquitectura anterior, cada clic recalculaba todo con SQL (`COUNT`, un `GROUP BY` por faceta y `LIMIT/OFFSET`). Eso hacía que la latencia creciera con el tamaño del catálogo y con la profundidad de la página, que la paginación repitiera u omitiera productos cuando cambiaba el inventario y que el comprador cayera en filtros sin resultados.

**Solución:** un modelo de lectura en memoria (índice invertido de máscaras + índices ordenados) mantenido por eventos, con navegación guiada por facetas con conteo, paginación por cursor e historial con deshacer instantáneo.

## Patrones de diseño aplicados

| Patrón | Dónde | Para qué |
|---|---|---|
| **Composite** | `app/patrones/composite_categorias.py` | Árbol de categorías: conteos y migas de pan sin distinguir hojas de grupos |
| **Strategy** | `strategy_orden.py`, `strategy_recorrido.py`, motores | Criterios de orden; recorrido ordenado vs extracción directa elegidos por un planificador de costo; perfil línea base vs optimizado |
| **Iterator** | `iterator_paginacion.py` | Páginas por `OFFSET` (base) o por cursor (optimizado) con la misma interfaz |
| **Command** (+ Memento) | `command_navegacion.py` | Cada acción del comprador es un objeto: atrás/adelante, historial y restauración instantánea |
| **Observer** | `observer_inventario.py`, `motores/optimizado.py` | Los cambios de inventario actualizan el índice de forma incremental |

## Ejecutar

```bash
pip install -r requirements.txt
CATALOGO_N=200000 uvicorn app.main:app --port 8000     # genera el catálogo la primera vez
# abrir http://localhost:8000  (botón «Línea base / Optimizado» arriba a la derecha)
```

## Pruebas y evaluación

```bash
python -m pytest -q                          # 12 pruebas: equivalencia de resultados y cada patrón
python -m scripts.benchmark                  # escenarios E1–E7 → resultados/benchmark.json
CATALOGO_N=200000 uvicorn app.main:app &     # y luego:
python -m scripts.prueba_carga               # carga HTTP concurrente → resultados/carga_http.json
python -m scripts.graficas                   # figuras → docs/figuras/
```

Los diagramas UML (PlantUML) están en `docs/uml/` (fuente `.puml` y exportados en PNG/SVG); las capturas del prototipo, en `docs/capturas/`.

## Estructura

```
app/
  catalogo_def.py        árbol, municipios, facetas (código ↔ SQL)
  datos.py               generación determinista del catálogo en SQLite
  main.py                API FastAPI + servidor de la interfaz web
  motores/               línea base (SQL) y optimizado (índice en memoria)
  patrones/              Composite, Strategy, Iterator, Command, Observer
web/index.html           interfaz de navegación con panel «Arquitectura en vivo»
scripts/                 benchmark, prueba de carga y gráficas
tests/                   pytest
docs/                    UML, figuras y capturas
resultados/              datos crudos de la evaluación
```
