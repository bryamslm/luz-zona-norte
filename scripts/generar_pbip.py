"""
Genera el reporte de Power BI como codigo: un proyecto PBIP (modelo semantico en
TMDL + reporte en PBIR) en powerbi/. Power BI Desktop lo abre directamente
(Archivo > Abrir > powerbi/LuzZonaNorte.pbip) y desde ahi se puede guardar como .pbix.

    python scripts/generar_pbip.py

Por que como codigo: el modelo, las medidas DAX y cada visual quedan versionados en
git y se pueden revisar en un diff, igual que el resto del pipeline.
"""
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "powerbi"
NAME = "LuzZonaNorte"
NS = uuid.UUID("2b7d4c1e-8a3f-4d6b-b1e2-7c9a0f5e3d21")


def tag(*parts: str) -> str:
    """lineageTag estable: mismo nombre -> mismo GUID en cada corrida."""
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    """Nombre TMDL/DAX: se cita si tiene espacios o caracteres no ASCII."""
    return name if name.isidentifier() and name.isascii() else "'" + name.replace("'", "''") + "'"


# --------------------------------------------------------------------------------------
# Modelo: tabla en Power BI -> (esquema, tabla SQL, columnas [(nombre, tipo, formato, oculta)])
# --------------------------------------------------------------------------------------
I, D, S, T, B = "int64", "double", "string", "dateTime", "boolean"
TABLES = {
    "Periodo": ("dw", "dim_periodo", [
        ("id_periodo", I, "0", True), ("anio", I, "0", False), ("mes", I, "0", False),
        ("nombre_mes", S, None, False), ("fecha", T, "mmm yyyy", False)]),
    "Empresa": ("dw", "dim_empresa", [
        ("cod_empresa", S, None, True), ("empresa", S, None, False), ("razon_social", S, None, False)]),
    "Tipo": ("dw", "dim_tipo", [
        ("tipo", I, "0", False), ("nombre", S, None, False), ("descripcion", S, None, False)]),
    "Circuito": ("dw", "dim_circuito", [
        ("id_circuito", I, "0", True), ("cod_empresa", S, None, True), ("circuito", S, None, True),
        ("nombre", S, None, False), ("primer_anio", I, "0", False), ("ultimo_anio", I, "0", False)]),
    "Distrito": ("dw", "dim_distrito", [
        ("cod_distrito", I, "0", True), ("provincia", S, None, False), ("canton", S, None, False),
        ("distrito", S, None, False), ("pct_en_concesion", D, "0%", False)]),
    "Planta": ("dw", "dim_planta", [("planta", S, None, False), ("cod_empresa", S, None, True)]),
    "Continuidad": ("dw", "fact_continuidad", [
        ("id_periodo", I, "0", True), ("cod_empresa", S, None, True), ("id_circuito", I, "0", True),
        ("tipo", I, "0", True), ("fpi", D, "#,0.00", True), ("dpir", D, "#,0.00", True),
        ("abonados", I, "#,0", True), ("fpi_x_abon", D, "#,0", True), ("dpir_x_abon", D, "#,0", True),
        ("meses", I, "0", True)]),
    "Lluvia": ("dw", "fact_lluvia", [
        ("cod_distrito", I, "0", True), ("id_periodo", I, "0", True), ("mm_era5", D, "#,0", True),
        ("mm_merra2", D, "#,0", True)]),
    "Generación": ("dw", "fact_generacion", [
        ("id_periodo", I, "0", True), ("planta", S, None, True), ("kwh", D, "#,0", True)]),
}

# (desde tabla.columna, hacia tabla.columna) — muchos a uno, filtro de la dimension al hecho.
RELATIONSHIPS = [
    ("Continuidad", "id_periodo", "Periodo", "id_periodo"),
    ("Continuidad", "cod_empresa", "Empresa", "cod_empresa"),
    ("Continuidad", "id_circuito", "Circuito", "id_circuito"),
    ("Continuidad", "tipo", "Tipo", "tipo"),
    ("Lluvia", "id_periodo", "Periodo", "id_periodo"), ("Lluvia", "cod_distrito", "Distrito", "cod_distrito"),
    ("Generación", "id_periodo", "Periodo", "id_periodo"), ("Generación", "planta", "Planta", "planta"),
    # Circuito -> Empresa NO se relaciona: Continuidad ya llega a Empresa directo y una
    # segunda ruta haria el modelo ambiguo.
]

# --------------------------------------------------------------------------------------
# Medidas DAX: (carpeta, nombre, expresion, formato, descripcion)
# --------------------------------------------------------------------------------------


def ponderado(col: str, tipo: int) -> str:
    """
    Indicador de continuidad agregable. Cada empresa reporta con su cadencia (mensual o
    semestral), asi que se suma por empresa y año: sum(indicador x abonados) / abonados
    promedio de los periodos reportados. Con varios años da el promedio anual.
    """
    return ("VAR t = SUMMARIZE('Continuidad', 'Continuidad'[cod_empresa], 'Periodo'[anio])\n"
            "VAR x = ADDCOLUMNS(t,\n"
            f"    \"@i\", CALCULATE(SUM('Continuidad'[{col}]), 'Continuidad'[tipo] = {tipo}),\n"
            "    \"@a\", CALCULATE([Abonados promedio]))\n"
            "RETURN DIVIDE(SUMX(x, [@i]), SUMX(x, [@a]))")


COOP = "'Empresa'[cod_empresa] = \"COOPELESCA\""


def ultimo(expr: str) -> str:
    """Evalua `expr` en el ultimo año con datos de continuidad (ARESEP publica con atraso)."""
    return ("VAR y = INT(CALCULATE(MAX('Continuidad'[id_periodo]), REMOVEFILTERS('Periodo')) / 100)\n"
            f"RETURN CALCULATE({expr}, 'Periodo'[anio] = y)")


MEASURES = [
    # Continuidad -----------------------------------------------------------------------
    ("Continuidad", "Abonados promedio",
     "AVERAGEX(VALUES('Continuidad'[id_periodo]),\n"
     "    CALCULATE(SUM('Continuidad'[abonados]), 'Continuidad'[tipo] = 1))", "#,0",
     "Abonados promedio de los periodos que la empresa reportó."),
    ("Continuidad", "FPI", ponderado("fpi_x_abon", 1), "#,0.00",
     "Frecuencia promedio de interrupciones por abonado en el año (todas las causas)."),
    ("Continuidad", "DPIR h", ponderado("dpir_x_abon", 1), "#,0.00",
     "Horas sin servicio por abonado en el año (todas las causas)."),
    ("Continuidad", "FPI sin ICE", ponderado("fpi_x_abon", 2), "#,0.00",
     "Tipo 2: excluye fallas de transmisión y generación (ICE)."),
    ("Continuidad", "FPI internas", ponderado("fpi_x_abon", 3), "#,0.00",
     "Tipo 3: excluye ICE y causas externas. Lo que depende de la red de la empresa."),
    ("Continuidad", "FPI por ICE", "[FPI] - [FPI sin ICE]", "#,0.00",
     "Interrupciones por fallas de transmisión o generación."),
    ("Continuidad", "FPI externas", "[FPI sin ICE] - [FPI internas]", "#,0.00",
     "Interrupciones por influencias ambientales, actividad humana o redes externas."),
    ("Continuidad", "% externas", "DIVIDE([FPI externas], [FPI])", "0.0%",
     "Peso de las causas externas en el total."),
    ("Continuidad", "Interrupciones (abonado-vez)",
     "CALCULATE(SUM('Continuidad'[fpi_x_abon]), 'Continuidad'[tipo] = 1)", "#,0",
     "Total de veces que un abonado quedó sin luz. Dónde pesa más el problema."),
    ("Continuidad", "FPI nacional", "CALCULATE([FPI], REMOVEFILTERS('Empresa'), REMOVEFILTERS('Circuito'))",
     "#,0.00", "Promedio de las ocho distribuidoras, ponderado por abonados."),
    # Coopelesca ------------------------------------------------------------------------
    ("Coopelesca", "FPI Coopelesca", f"CALCULATE([FPI], {COOP})", "#,0.00", "FPI de Coopelesca."),
    ("Coopelesca", "FPI externas Coopelesca", f"CALCULATE([FPI externas], {COOP})", "#,0.00",
     "Interrupciones de causa externa en Coopelesca."),
    ("Coopelesca", "FPI internas Coopelesca", f"CALCULATE([FPI internas], {COOP})", "#,0.00",
     "Interrupciones de causa interna en Coopelesca."),
    ("Coopelesca", "Interrupciones Coopelesca", f"CALCULATE([Interrupciones (abonado-vez)], {COOP})", "#,0",
     "Interrupciones abonado-vez en los circuitos de Coopelesca."),
    ("Coopelesca", "DPIR Coopelesca h", f"CALCULATE([DPIR h], {COOP})", "#,0.00", "DPIR de Coopelesca."),
    ("Coopelesca", "FPI Coopelesca (último año)", ultimo("[FPI Coopelesca]"), "#,0.00",
     "FPI del último año publicado por ARESEP."),
    ("Coopelesca", "DPIR Coopelesca h (último año)", ultimo("[DPIR Coopelesca h]"), "#,0.00",
     "Horas sin luz por abonado en el último año publicado."),
    ("Coopelesca", "% externas Coopelesca (último año)", ultimo(f"[% externas], {COOP}"), "0.0%",
     "Peso de las causas externas en Coopelesca, último año."),
    ("Coopelesca", "FPI internas Coopelesca (último año)", ultimo("[FPI internas Coopelesca]"), "#,0.00",
     "Interrupciones por causas internas en Coopelesca, último año."),
    ("Coopelesca", "FPI nacional (último año)", ultimo("[FPI nacional]"), "#,0.00",
     "FPI nacional del último año publicado."),
    ("Coopelesca", "Interrupciones Coopelesca (último año)", ultimo("[Interrupciones Coopelesca]"), "#,0",
     "Interrupciones abonado-vez del último año publicado."),
    ("Coopelesca", "FPI externas Coopelesca (mensual)",
     f"IF(CALCULATE(MAX('Continuidad'[meses]), {COOP}) = 1, [FPI externas Coopelesca])", "#,0.00",
     "Solo periodos mensuales: un valor semestral (2020-2022) no es comparable con un mes."),
    ("Clima y generación", "Lluvia anual promedio mm", "AVERAGEX(VALUES('Periodo'[anio]), [Lluvia zona mm])",
     "#,0", "Lluvia anual de la zona, promedio de los años seleccionados con datos."),
    # Clima y generacion ----------------------------------------------------------------
    ("Clima y generación", "Lluvia zona mm",
     "AVERAGEX(VALUES('Distrito'[cod_distrito]), CALCULATE(SUM('Lluvia'[mm_era5])))", "#,0",
     "Lluvia promedio de los distritos de la concesión de Coopelesca (ERA5, Open-Meteo)."),
    ("Clima y generación", "Lluvia zona mm (MERRA-2)",
     "AVERAGEX(VALUES('Distrito'[cod_distrito]), CALCULATE(SUM('Lluvia'[mm_merra2])))", "#,0",
     "Contraste: NASA POWER. Subestima la lluvia de la zona; no se usa en el análisis."),
    ("Clima y generación", "Generación GWh", "DIVIDE(SUM('Generación'[kwh]), 1000000)", "#,0.0",
     "Energía generada por las plantas de Coopelesca (ARESEP)."),
]


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def semantic_model():
    sm = OUT / f"{NAME}.SemanticModel"
    write(sm / "definition.pbism", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {"qnaEnabled": False}}, indent=2))
    d = sm / "definition"
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n")
    refs = "\n".join(f"ref table {q(t)}" for t in [*TABLES, "Medidas"])
    write(d / "model.tmdl",
          "model Model\n\tculture: es-ES\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
          "\tdiscourageImplicitMeasures\n\tsourceQueryCulture: es-ES\n\tdataAccessOptions\n"
          "\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
          f"annotation PBI_QueryOrder = {json.dumps(['Servidor', 'BaseDatos', *TABLES], ensure_ascii=False)}\n\n"
          f"{refs}\n")
    write(d / "expressions.tmdl",
          "/// Servidor SQL Server. Por defecto, el tunel SSH local hacia el servidor del proyecto.\n"
          "expression Servidor = \"127.0.0.1,14333\" meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
          f"\tlineageTag: {tag('expr', 'Servidor')}\n\n\tannotation PBI_ResultType = Text\n\n"
          "expression BaseDatos = \"luz_zona_norte\" meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
          f"\tlineageTag: {tag('expr', 'BaseDatos')}\n\n\tannotation PBI_ResultType = Text\n")

    for table, (schema, sql_table, cols) in TABLES.items():
        lines = [f"table {q(table)}", f"\tlineageTag: {tag('t', table)}", ""]
        for name, dtype, fmt, hidden in cols:
            lines.append(f"\tcolumn {q(name)}")
            lines.append(f"\t\tdataType: {dtype}")
            if hidden:
                lines.append("\t\tisHidden")
            if fmt:
                lines.append(f"\t\tformatString: {fmt}")
            lines.append(f"\t\tlineageTag: {tag('c', table, name)}")
            lines.append("\t\tsummarizeBy: none")
            lines.append(f"\t\tsourceColumn: {name}")
            lines.append("")
            lines.append("\t\tannotation SummarizationSetBy = Automatic")
            lines.append("")
        lines += [
            f"\tpartition {q(table)} = m",
            "\t\tmode: import",
            "\t\tsource =",
            "\t\t\t\tlet",
            "\t\t\t\t    Source = Sql.Database(Servidor, BaseDatos),",
            f"\t\t\t\t    Tabla = Source{{[Schema=\"{schema}\",Item=\"{sql_table}\"]}}[Data]",
            "\t\t\t\tin",
            "\t\t\t\t    Tabla",
            "",
            "\tannotation PBI_ResultType = Table",
            "",
        ]
        write(d / "tables" / f"{table}.tmdl", "\n".join(lines))

    # Tabla de medidas: una tabla calculada de una fila, oculta, que solo agrupa las medidas.
    lines = ["/// Todas las medidas del reporte, agrupadas por pagina en carpetas.", "table Medidas",
             f"\tlineageTag: {tag('t', 'Medidas')}", ""]
    for folder, name, expr, fmt, desc in MEASURES:
        lines.append(f"\t/// {desc}")
        if "\n" in expr:
            lines.append(f"\tmeasure {q(name)} =")
            lines += ["\t\t\t" + l for l in expr.split("\n")]
        else:
            lines.append(f"\tmeasure {q(name)} = {expr}")
        lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tdisplayFolder: {folder}")
        lines.append(f"\t\tlineageTag: {tag('m', name)}")
        lines.append("")
    lines += ["\tcolumn _", "\t\tdataType: int64", "\t\tisHidden", "\t\tformatString: 0",
              f"\t\tlineageTag: {tag('c', 'Medidas', '_')}", "\t\tsummarizeBy: none",
              "\t\tisNameInferred", "\t\tsourceColumn: [_]", "",
              "\tpartition Medidas = calculated", "\t\tmode: import", "\t\tsource = ROW(\"_\", 0)", "",
              "\tannotation PBI_Id = medidas", ""]
    write(d / "tables" / "Medidas.tmdl", "\n".join(lines))

    rels = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rels += [f"relationship {tag('r', ft, fc, tt, tc)}",
                 f"\tfromColumn: {q(ft)}.{q(fc)}", f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    write(d / "relationships.tmdl", "\n".join(rels))


# --------------------------------------------------------------------------------------
# Reporte PBIR
# --------------------------------------------------------------------------------------
AZUL, AMBAR, INK, MUTED = "#1B3A5C", "#E8A317", "#14202B", "#5C6670"
LLUVIA, INTERNAS, FONDO = "#3F88C5", "#C1440E", "#F5F6F4"


def lit(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def measure(name: str) -> dict:
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Medidas"}}, "Property": name}},
            "queryRef": f"Medidas.{name}", "nativeQueryRef": name}


def column(table: str, name: str) -> dict:
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
            "queryRef": f"{table}.{name}", "nativeQueryRef": name}


def container(vid: str, x, y, w, h, z, visual: dict) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": vid, "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": visual,
    }


def title_obj(text: str) -> dict:
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'"),
                                      "fontSize": lit("12D"), "fontColor": {"solid": {"color": lit(f"'{INK}'")}}}}]}


def textbox(text: str, size: str, color: str, bold: bool = False, extra: list | None = None) -> dict:
    runs = [{"value": text, "textStyle": {"fontFamily": "Segoe UI Semibold" if bold else "Segoe UI",
                                          "fontSize": size, "color": color}}]
    paragraphs = [{"textRuns": runs}]
    for t, s, c in extra or []:
        paragraphs.append({"textRuns": [{"value": t, "textStyle": {"fontFamily": "Segoe UI", "fontSize": s, "color": c}}]})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "drillFilterOtherVisuals": True}


def card(measures: list[str]) -> dict:
    return {
        "visualType": "cardVisual",
        "query": {"queryState": {"Data": {"projections": [measure(m) for m in measures]}}},
        "objects": {
            "layout": [{"properties": {"orientation": lit("0D"), "columnCount": lit(f"{len(measures)}L"),
                                       "alignment": lit("'middle'"), "style": lit("'Cards'")}}],
            "value": [{"properties": {"fontSize": lit("26D"), "labelDisplayUnits": lit("1D"),
                                      "fontColor": {"solid": {"color": lit(f"'{AZUL}'")}}},
                       "selector": {"id": "default"}}],
            "accentBar": [{"properties": {"show": lit("true"),
                                          "color": {"solid": {"color": lit(f"'{AMBAR}'")}}},
                           "selector": {"id": "default"}}],
        },
        "visualContainerObjects": {"title": [{"properties": {"show": lit("false")}}]},
        "drillFilterOtherVisuals": True,
    }


def chart(vtype: str, category: dict, values: list[str], title: str, sort_by: str | None = None) -> dict:
    query = {"queryState": {"Category": {"projections": [{**category, "active": True}]},
                            "Y": {"projections": [measure(m) for m in values]}}}
    if sort_by:
        query["sortDefinition"] = {"sort": [{"field": measure(sort_by)["field"], "direction": "Descending"}],
                                   "isDefaultSort": True}
    axis = {"showAxisTitle": lit("false")}
    # columnas: anos como categoria (pocas mediciones); lineas: eje continuo (hasta 64 anos)
    if vtype != "lineChart" and category["field"]["Column"]["Property"] in ("anio", "periodo"):
        axis["axisType"] = lit("'Categorical'")
    objects = {"categoryAxis": [{"properties": axis}],
               "valueAxis": [{"properties": {"showAxisTitle": lit("false")}}]}
    if len(values) > 1:
        objects["legend"] = [{"properties": {"show": lit("true"), "position": lit("'Top'")}}]
    return {"visualType": vtype, "query": query, "objects": objects,
            "visualContainerObjects": title_obj(title), "drillFilterOtherVisuals": True}


def table_visual(cols: list[dict], title: str) -> dict:
    return {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": cols}}},
            "visualContainerObjects": title_obj(title), "drillFilterOtherVisuals": True}


def slicer(col: dict, title: str, mode: str = "Basic") -> dict:
    return {"visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [{**col, "active": True}]}}},
            "objects": {"data": [{"properties": {"mode": lit(f"'{mode}'")}}],
                        "header": [{"properties": {"show": lit("false")}}]},
            "visualContainerObjects": title_obj(title), "drillFilterOtherVisuals": True}


FUENTES = ("Fuentes: ARESEP (indicadores de continuidad y generación por planta, datos abiertos), IGN, "
           "Open-Meteo (ERA5), NASA POWER. Pipeline y validaciones: github.com/bryamslm/luz-zona-norte")

PAGES = [
    ("panorama", "1 · Panorama", "Coopelesca frente al resto del país",
     "FPI: veces que un abonado se quedó sin luz en el año. DPIR: horas sin luz. Ocho distribuidoras, 2019-2024.",
     ["FPI Coopelesca (último año)", "DPIR Coopelesca h (último año)", "% externas Coopelesca (último año)",
      "FPI nacional (último año)"],
     [("clusteredColumnChart", column("Periodo", "anio"), ["FPI Coopelesca", "FPI nacional"],
       "Interrupciones por abonado: Coopelesca contra el país", None),
      ("clusteredBarChart", column("Empresa", "empresa"), ["FPI"], "FPI por distribuidora", "FPI")],
     slicer(column("Periodo", "anio"), "Año", "Between")),
    ("causas", "2 · Causas", "Por qué se va la luz",
     "Descomposición oficial de ARESEP: fallas del ICE, causas externas (ambiente, actividad humana, redes ajenas) e internas.",
     ["FPI por ICE", "FPI externas", "FPI internas", "% externas"],
     [("columnChart", column("Periodo", "anio"), ["FPI por ICE", "FPI externas", "FPI internas"],
       "Interrupciones por abonado según su causa", None),
      ("clusteredBarChart", column("Empresa", "empresa"), ["FPI internas"],
       "Interrupciones por causas internas (la red de cada empresa)", "FPI internas")],
     slicer(column("Empresa", "empresa"), "Distribuidora")),
    ("circuitos", "3 · Circuitos", "Dónde se concentra el problema en Coopelesca",
     "Interrupciones abonado-vez: cuántas veces, en total, un abonado del circuito quedó sin luz. Último año publicado.",
     ["Interrupciones Coopelesca (último año)", "FPI Coopelesca (último año)", "DPIR Coopelesca h (último año)"],
     [("clusteredBarChart", column("Circuito", "nombre"), ["Interrupciones Coopelesca (último año)"],
       "Circuitos por interrupciones totales", "Interrupciones Coopelesca (último año)"),
      ("clusteredBarChart", column("Circuito", "nombre"), ["DPIR Coopelesca h (último año)"],
       "Circuitos por horas sin luz por abonado", "DPIR Coopelesca h (último año)")],
     slicer(column("Circuito", "nombre"), "Circuito")),
    ("lluvia", "4 · Lluvia", "¿La lluvia explica los cortes?",
     "Coopelesca reportó mes a mes en 2019, 2023 y 2024; en 2020-2022 lo hizo por semestre y esos años no se grafican.",
     ["Lluvia anual promedio mm", "FPI externas Coopelesca", "% externas Coopelesca (último año)"],
     [("lineChart", column("Periodo", "fecha"), ["FPI externas Coopelesca (mensual)"],
       "Interrupciones por causa externa, por mes", None),
      ("lineChart", column("Periodo", "fecha"), ["Lluvia zona mm"],
       "Lluvia mensual en la zona de concesión (mm, ERA5)", None)],
     slicer(column("Periodo", "anio"), "Año", "Between")),
    ("generacion", "5 · Generación", "Las plantas de Coopelesca y la lluvia",
     "Energía mensual de sus cinco plantas hidroeléctricas (ARESEP). Platanar entra en 2021 y Pocosol en 2020.",
     ["Generación GWh", "Lluvia anual promedio mm"],
     [("lineChart", column("Periodo", "fecha"), ["Generación GWh"], "Generación mensual (GWh)", None),
      ("clusteredBarChart", column("Planta", "planta"), ["Generación GWh"], "Generación por planta (GWh)",
       "Generación GWh")],
     slicer(column("Periodo", "anio"), "Año", "Between")),
]


def report():
    rp = OUT / f"{NAME}.Report"
    write(rp / "definition.pbir", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    d = rp / "definition"
    write(d / "version.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"}, indent=2))
    write(d / "report.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": {"visual": "1.8.97", "report": "2.0.97", "page": "1.3.97"},
                          "type": "SharedResources"},
            "customTheme": {"name": "luz.json", "reportVersionAtImport": {"visual": "1.8.100", "report": "2.0.100", "page": "1.3.100"},
                            "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "luz.json", "path": "luz.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultFilterActionIsDataFilter": True,
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True},
    }, indent=2))
    write(rp / "StaticResources" / "RegisteredResources" / "luz.json", json.dumps({
        "name": "Luz zona norte",
        "dataColors": [AZUL, AMBAR, INTERNAS, LLUVIA, "#7B8794", "#2A9D8F", "#9C6644", "#B8C4CF"],
        "background": FONDO, "foreground": INK, "tableAccent": AZUL,
        "maximum": AZUL, "center": AMBAR, "minimum": "#E6EAEE",
    }, indent=2, ensure_ascii=False))

    write(d / "pages" / "pages.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p[0] for p in PAGES], "activePageName": PAGES[0][0]}, indent=2))

    for pid, display, heading, subtitle, cards, charts, page_slicer in PAGES:
        pdir = d / "pages" / pid
        write(pdir / "page.json", json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.4.0/schema.json",
            "name": pid, "displayName": display, "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": {"solid": {"color": lit(f"'{FONDO}'")}},
                                                       "transparency": lit("0D")}}]},
        }, indent=2, ensure_ascii=False))
        heading_color = INK
        visuals = {
            "titulo": container(f"{pid}titulo", 24, 12, 960, 76, 1000,
                                textbox(heading, "22pt", heading_color, True, [(subtitle, "10pt", MUTED)])),
            "filtro": container(f"{pid}filtro", 1000, 16, 256, 76, 2000, page_slicer),
            "tarjetas": container(f"{pid}tarjetas", 24, 100, 1232, 120, 3000, card(cards)),
            "fuentes": container(f"{pid}fuentes", 24, 684, 1232, 28, 9000, textbox(FUENTES, "8pt", MUTED)),
        }
        (vt1, cat1, val1, t1, s1), (vt2, cat2, val2, t2, s2) = charts
        visuals["grafico1"] = container(f"{pid}grafico1", 24, 236, 700, 440, 4000, chart(vt1, cat1, val1, t1, s1))
        visuals["grafico2"] = container(f"{pid}grafico2", 740, 236, 516, 440, 5000, chart(vt2, cat2, val2, t2, s2))
        for vid, v in visuals.items():
            write(pdir / "visuals" / vid / "visual.json", json.dumps(v, indent=2, ensure_ascii=False))


def main():
    if OUT.exists():
        # se conserva cualquier .pbix guardado a mano; se regenera solo el proyecto
        for p in OUT.glob(f"{NAME}.*"):
            if p.is_dir():
                shutil.rmtree(p)
    OUT.mkdir(exist_ok=True)
    semantic_model()
    report()
    write(OUT / f"{NAME}.pbip", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    n_vis = sum(1 for _ in (OUT / f"{NAME}.Report").rglob("visual.json"))
    print(f"PBIP generado en {OUT}: {len(TABLES) + 1} tablas, {len(RELATIONSHIPS)} relaciones, "
          f"{len(MEASURES)} medidas, {len(PAGES)} paginas, {n_vis} visuales")


if __name__ == "__main__":
    main()
