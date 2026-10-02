# Luz zona norte · por qué se va la luz

¿Dónde y cuándo se va la luz en la zona de Coopelesca, y cuánto se explica por la lluvia?
Se responde con datos abiertos de ARESEP, un modelo estrella en **SQL Server** y un reporte de
**Power BI** de cinco páginas.

**En vivo:** [luz.bryamlopez.com](https://luz.bryamlopez.com) ·
**Reporte:** [`powerbi/`](powerbi/) (proyecto PBIP: modelo en TMDL y páginas en PBIR)

## Qué responde

| Pregunta | Respuesta (verificada) |
|---|---|
| ¿Cuántas veces se va la luz? | En 2024, cada abonado de Coopelesca se quedó sin luz **6,51 veces**, contra 7,71 del promedio nacional. |
| ¿Por culpa de quién? | **0,50** por causas internas (su red), **5,92** por causas externas (ambiente, actividad humana, redes ajenas) y 0,09 por fallas del ICE. El **91 %** es externo. |
| ¿Es buena su red? | En 2024 tuvo la menor frecuencia de cortes internos de las ocho distribuidoras, y desde 2021 siempre está entre las dos más bajas. |
| ¿Y cuánto duran? | **12,2 horas** sin luz por abonado en 2024: la más alta del país ese año. |
| ¿Dónde se concentra? | **5 de 30 circuitos suman el 51 %** de las interrupciones de 2024. Santa Rosa encabeza la lista. |
| ¿Qué pasó en 2023? | Fue su peor año (11,87), pero un solo dato atípico (Marina, septiembre) aporta 3,4 puntos. Sin él, 8,52. |
| ¿La lluvia explica los cortes? | Poco. Hay 63 % más cortes externos en la época lluviosa, pero el pico es en junio y julio, no en los meses más lluviosos. Mes a mes, ρ = 0,38 (p = 0,027, 35 meses). |
| ¿Y la generación? | Ahí sí manda la lluvia: ρ = 0,66 (84 meses). En 2023, el año más seco, sus tres plantas más antiguas generaron 29 % menos que en 2022. |

## Arquitectura

```
FUENTES                            INGESTA               ALMACÉN                 MODELO             CONSUMO
ARESEP continuidad (API)       ─┐                        SQL Server 2022
ARESEP generación (API)        ─┤  descargar.py          dw.*  modelo estrella   Power BI           Reporte PBIP
ARESEP zonas de concesión      ─┼─ procesar.py      ──►  vistas v_* de KPI  ──►  10 tablas,     ─►  luz.
IGN límites distritales (WFS)  ─┤  indicadores.py        login solo lectura      26 medidas DAX     bryamlopez.com
Open-Meteo ERA5 / NASA POWER   ─┘
```

- **Almacén:** SQL Server 2022 en un contenedor del servidor. Escucha solo en `localhost` y se
  accede por túnel SSH.
- **Modelo estrella:** dimensiones `Periodo`, `Empresa`, `Tipo` (causa), `Circuito`, `Distrito` y
  `Planta`. Hechos de continuidad (circuito × mes × tipo), lluvia (distrito × mes) y generación
  (planta × mes).
- **Una sola regla de cálculo en tres lugares:** `scripts/indicadores.py` (web), la vista
  `dw.v_continuidad_empresa_anual` (SQL) y las medidas DAX aplican la misma fórmula:

  > FPI de un grupo en un año = Σ (FPI × abonados) / abonados promedio de los periodos reportados

  Así se pueden comparar las empresas que reportan cada mes con las que reportan cada semestre, y
  un circuito recién energizado no pesa como uno grande.

## Las cinco páginas del reporte

| Página | Qué muestra |
|---|---|
| 1 · Panorama | Coopelesca contra el país, FPI por distribuidora |
| 2 · Causas | ICE, externas e internas por año y por empresa |
| 3 · Circuitos | Interrupciones totales y horas sin luz por circuito, último año |
| 4 · Lluvia | Cortes externos mes a mes contra la lluvia de la zona |
| 5 · Generación | Energía de las cinco plantas de Coopelesca |

## Controles contra cifras publicadas

| Control | Calculado | Publicado |
|---|---|---|
| FPI nacional 2024 | 7,71 | 7,63 ([ARESEP vía Semanario Universidad](https://semanariouniversidad.com/pais/servicio-electrico-mejoro-en-2025-pero-aun-castiga-a-usuarios-de-zonas-costeras-y-rurales/)) |
| DPIR nacional 2022 | 8,11 h | 8 h 22 min ([ARESEP](https://aresep.go.cr/noticias/mejora-la-continuidad-del-servicio-electrico-en-costa-rica/)) |
| Lluvia anual de la zona (ERA5) | 3.967 mm | 3.172 ± 659 mm, Zona Norte ([IMN](https://www.imn.ac.cr/documents/10179/31165/ZonaNorte.pdf/c08ed9c6-3d27-4f76-a20a-7cac913fb6d8)) |

Los controles corren solos al final de `cargar.py`, que falla si alguno sale de tolerancia.

## Errores encontrados en las fuentes

El detalle está en [`docs/calidad-de-datos.md`](docs/calidad-de-datos.md). Los principales:

1. **El significado de las causas no está en el portal.** Lo encontré en la plantilla oficial
   PCE 05 de ARESEP.
2. **Cadencias mezcladas:** sumar meses sin cuidado da un FPI nacional de 11,6 en lugar de alrededor
   de 8.
3. **Circuitos repetidos** con filas vacías: promediarlos partiría el valor a la mitad.
4. **Dos meses atípicos** que dominan los promedios simples.
5. **Las dos fuentes abiertas de lluvia no coinciden:** MERRA-2 da menos de la mitad que ERA5.
6. **Generación duplicada,** a veces con valores distintos para la misma planta y mes.

## Cómo correrlo

```bash
python -m pip install -r requirements.txt
cp .env.example .env                       # completar las contraseñas
ssh -f -N -L 14333:127.0.0.1:14333 bryam   # túnel al SQL Server

python scripts/descargar.py     # fuentes crudas a data/raw (idempotente)
python scripts/procesar.py      # modelo estrella a data/clean
python scripts/cargar.py        # SQL Server + controles
python scripts/generar_pbip.py  # reporte de Power BI como código
python scripts/exportar_web.py  # datos de la página web
```

Para abrir el reporte: **Power BI Desktop → Archivo → Abrir → `powerbi/LuzZonaNorte.pbip`**. En
las credenciales de SQL Server, elegí **Base de datos** y usá el usuario `luz_bi`.

## Límites

- ARESEP todavía no publica 2025.
- Las causas externas juntan ambiente, actividad humana y redes ajenas. Los datos abiertos no las
  separan, así que no se puede decir cuánto es por árboles, rayos o choques contra postes.
- La lluvia es de un reanálisis (malla), no de estaciones del IMN.
- Los circuitos no tienen coordenadas, así que la lluvia se mide para toda la zona de concesión y
  no por circuito.
- No se usó ningún dato interno de Coopelesca: todo es información pública.

---

Hecho por [Bryam López](https://linkedin.com/in/bryamslm), ingeniero en Computación (TEC).
