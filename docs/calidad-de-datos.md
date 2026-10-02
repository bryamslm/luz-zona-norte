# Calidad de datos: lo que se encontró en las fuentes

Cada regla de `scripts/procesar.py` responde a uno de estos problemas. Todos se pueden reproducir
con los archivos de `data/raw`.

## ARESEP: indicadores de continuidad

1. **El significado de `tipoIndicador` no está en el portal de datos abiertos.** El metadato solo
   dice "incluye o excluye interrupciones según su causa". La definición está en la plantilla
   **PCE 05 Indicadores de continuidad (RE-0006-IE-2024)**, hoja *CATALOGO TIPO DE INDICADOR*:

   | Tipo | Nombre | Qué incluye |
   |---|---|---|
   | 1 | Total | Todas las interrupciones. |
   | 2 | Total − ICE | Excluye las fallas de transmisión, la falta de generación y las salidas por frecuencia o estabilidad. |
   | 3 | Total − ICE − Externas | Excluye además las causas externas: influencias ambientales, de la actividad humana y de redes eléctricas externas (art. 70 de la AR-NT-SUCAL). |
   | 4 | Total − Exentas | Excluye las interrupciones exentas de compensación. |

   Con eso: **ICE = 1 − 2**, **externas = 2 − 3** e **internas = 3**. No hay que confundirlo con los
   "niveles I a IV" de la norma (tabla 12), que indican **dónde** ocurre el corte en la red, no su causa.

2. **El tipo 4 solo trae valores de Coopelesca en 2024.** Las demás empresas lo reportan en cero.
   Se carga, pero no se usa en la descomposición por causa.

3. **Cadencias mezcladas.** En un mismo año, unas empresas reportan mes a mes y otras solo en junio
   y diciembre, con el valor del semestre. Sumar los meses de todo el país da un FPI nacional de
   11,6 para 2019, cuando ARESEP reporta alrededor de 8. Por eso el FPI se calcula **por empresa y
   año** (suma de FPI × abonados entre los abonados promedio de sus periodos), y el nacional es el
   promedio de las empresas ponderado por abonados. Con esa regla, 2024 da **7,71 contra 7,63
   publicado**.

4. **Coopelesca reportó por semestre en 2020-2022.** Esos años entran en los totales anuales, pero
   no en el análisis mes a mes contra la lluvia.

5. **ESPH 2023 solo trae el primer semestre.** Su FPI de 2023 cubre medio año y se subestima.

6. **ICE repite circuitos en un mismo mes** (53 filas en 2019 y 2024): una fila real y copias vacías
   con 0 abonados. Promediar partiría el valor a la mitad, así que se suman productos y abonados y
   se descartan las filas sin abonados.

7. **Nombres con espacios al inicio:** `" PITAL"` y `"PITAL"`. Se recortan.

8. **Coopelesca reorganizó sus circuitos en julio de 2024:** pasó de 20 a 30. Coopevega, Boca
   Arenal y San Jorge empiezan en julio, y Marina baja de 8.016 a 347 abonados. El ranking anual
   usa abonados promedio del año.

9. **Dos meses atípicos en Coopelesca:**
   - **Marina, septiembre de 2023:** FPI de 49,02 en un mes con 8.025 abonados, con un DPIR de 8,42 h
     (unos 10 minutos por corte). Solo ese dato explica 3,4 de los 11,87 puntos del año. Puede ser
     real o un error de digitación: **no verificado**. Se muestra con y sin él (11,87 contra 8,52).
   - **Cerro Cortés, mayo de 2024:** FPI de 57,28 con 57 abonados. Es un circuito recién energizado:
     ponderado por abonados casi no pesa.

10. **2025 y 2026 no están publicados.** El endpoint responde `"value": null`. El metadato del portal
    dice "cobertura 2017-2020", pero en realidad trae de 2019 a 2024; 2017 y 2018 vienen vacíos.

## ARESEP: generación por planta

11. **Filas duplicadas**, idénticas o con valores distintos para la misma planta y mes. Se quitan
    las idénticas y, si quedan versiones distintas, se conserva la última publicada.
12. **Plantas que entran a mitad del periodo:** Pocosol en 2020 y Platanar a finales de 2021. Para
    comparar años se usan solo Aguas Zarcas, Chocosuelas y La Esperanza, que están completas desde
    2019.

## Lluvia

13. **Las dos fuentes abiertas no coinciden.** En los mismos 22 puntos, NASA POWER (MERRA-2) da entre
    1.484 y 3.809 mm al año. Open-Meteo (ERA5) da entre 3.264 y 4.413 mm. Mes a mes, su correlación
    es de 0,44. El IMN publica para la Zona Norte un promedio de **3.172 ± 659 mm**: ERA5 queda dentro
    de 1,5 desviaciones y MERRA-2 casi siempre por debajo. **Se usa ERA5**, y MERRA-2 queda solo
    como contraste.
14. **Sin estaciones.** El IMN cobra por los datos de sus estaciones. El reanálisis es una malla, y
    no es lo mismo que un pluviómetro.
15. **Los circuitos no traen coordenadas** y el IGN no publica una capa abierta de poblados. Por eso
    la lluvia se mide para toda la zona: el promedio de los 22 distritos con al menos 20 % de su
    área dentro de la concesión que Coopelesca reportó a ARESEP.
