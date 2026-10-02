"""
Convierte data/raw en el modelo estrella de data/clean (CSV), listo para SQL Server.

    python scripts/procesar.py

Reglas (cada una responde a un problema de la fuente, ver docs/calidad-de-datos.md):
- Nombres de circuito con espacios al inicio (" PITAL" y "PITAL"): se recortan.
- Cada empresa reporta con su propia cadencia: mensual, o semestral en junio y diciembre.
  La fila guarda cuantos meses cubre (`meses`) y el FPI anual se arma por empresa.
- El tipo de indicador 4 ("Total - Exentas") solo trae valores de Coopelesca en 2024:
  queda en el modelo pero no entra en la descomposicion por causa.
- Generacion: ARESEP repite filas de la misma planta y mes. Se quitan las identicas y,
  si quedan dos versiones distintas, se conserva la ultima publicada.
"""
import json
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"

UMBRAL_CONCESION = 0.2  # un distrito entra si al menos 20 % de su area esta en la concesion

# Definicion oficial: plantilla PCE 05 "Indicadores de continuidad" (ARESEP, RE-0006-IE-2024),
# hoja CATALOGO TIPO DE INDICADOR.
TIPOS = [
    (1, "Total", "Todas las interrupciones, sin importar la causa u origen."),
    (2, "Total sin ICE", "Excluye las originadas por falta de suministro o fallas en la red de "
                         "transmisión, falta de abastecimiento de generación, salidas por frecuencia, estabilidad, etc."),
    (3, "Total sin ICE ni externas", "Excluye además las causas externas: influencias ambientales, de la "
                                     "actividad humana y de redes eléctricas externas (art. 70, AR-NT-SUCAL)."),
    (4, "Total sin exentas", "Excluye las interrupciones exentas de compensación."),
]

EMPRESAS = {  # nombre en continuidad -> (codigo, nombre largo usado en generacion)
    "ICE": ("ICE", "INSTITUTO COSTARRICENSE DE ELECTRICIDAD"),
    "CNFL": ("CNFL", "COMPAÑIA NACIONAL DE FUERZA Y LUZ S.A."),
    "Coopelesca": ("COOPELESCA", "COOPERATIVA DE ELECTRIFICACION RURAL DE SAN CARLOS R.L."),
    "Coopeguanacaste": ("COOPEGUANACASTE", "COOPERATIVA DE ELECTRIFICACION RURAL DE GUANACASTE R.L."),
    "Coopesantos": ("COOPESANTOS", "COOPERATIVA DE ELECTRIFICACION RURAL LOS SANTOS R.L."),
    "Coopealfaroruiz": ("COOPEALFARORUIZ", "COOPERATIVA DE ELECTRIFICACION RURAL DE ALFARO RUIZ R.L."),
    "JASEC": ("JASEC", "JUNTA ADMINISTRATIVA DEL SERVICIO ELECTRICO MUNICIPAL DE CARTAGO"),
    "ESPH": ("ESPH", "EMPRESA DE SERVICIOS PUBLICOS DE HEREDIA S.A."),
}
# Plantas que Coopelesca opera. Cubujuquí es de un consorcio de cooperativas y "Cutres"
# aparece un solo mes de 2019: se dejan fuera del analisis de su generacion.
PLANTAS_COOPELESCA = {"AGUAS ZARCAS": "Aguas Zarcas", "CHOCOSUELAS": "Chocosuelas",
                      "LA ESPERANZA": "La Esperanza", "PLATANAR": "Platanar", "POCOSOL": "Pocosol"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()


def leer_anios(carpeta: str) -> pd.DataFrame:
    return pd.concat([pd.DataFrame(json.loads(f.read_text(encoding="utf-8"))["value"])
                      for f in sorted((RAW / carpeta).glob("*.json"))], ignore_index=True)


def distritos_concesion() -> gpd.GeoDataFrame:
    zonas = json.loads((RAW / "concesion.json").read_text(encoding="utf-8"))["value"]
    zona = wkt.loads(next(z for z in zonas if z["operador"] == "COOPELESCA")["coordenadas"])
    d = gpd.read_file(RAW / "limitedistrital_5k.geojson").set_crs(5367, allow_override=True)
    d["pct_en_concesion"] = d.intersection(zona).area / d.area
    d = d[d["pct_en_concesion"] >= UMBRAL_CONCESION].copy()
    d["cod_distrito"] = d["CÓDIGO_DTA"].astype(int)
    return d.rename(columns={"PROVINCIA": "provincia", "CANTÓN": "canton", "DISTRITO": "distrito"})[
        ["cod_distrito", "provincia", "canton", "distrito", "pct_en_concesion", "geometry"]]


def continuidad() -> tuple[pd.DataFrame, pd.DataFrame]:
    c = leer_anios("continuidad")
    c["empresa"] = c["empresa"].str.strip()
    c["circuito"] = c["circuito"].map(norm)
    c["tipo"] = c["tipoIndicador"].astype(int)
    c = c.drop(columns="mes").rename(columns={"anho": "anio", "id_Mes": "mes", "abonadosPorCircuito": "abonados"})
    assert set(c["empresa"]) <= set(EMPRESAS), set(c["empresa"]) - set(EMPRESAS)

    # productos ponderados: el FPI de un grupo de circuitos es sum(fpi*abonados)/sum(abonados)
    c["fpi_x_abon"] = c["fpi"] * c["abonados"]
    c["dpir_x_abon"] = c["dpir"] * c["abonados"]
    # ICE repite algunos circuitos en el mismo mes: una fila real y otras vacias con 0 abonados.
    # Sumar productos y abonados deja la fila real intacta (promediar la partiria a la mitad).
    llave = ["anio", "mes", "empresa", "circuito", "tipo"]
    dup = c.duplicated(llave, keep=False)
    if dup.any():
        print(f"  continuidad: {dup.sum()} filas repetidas por llave, se consolidan")
    c = c.groupby(llave, as_index=False)[["fpi_x_abon", "dpir_x_abon", "abonados"]].sum()
    c = c[c["abonados"] > 0]
    c["fpi"] = (c["fpi_x_abon"] / c["abonados"]).round(4)
    c["dpir"] = (c["dpir_x_abon"] / c["abonados"]).round(4)

    # cadencia de cada empresa en cada año: 12 meses -> mensual; solo junio y diciembre -> semestral
    meses_rep = c.groupby(["anio", "empresa"])["mes"].nunique()
    c["meses"] = c.set_index(["anio", "empresa"]).index.map(lambda k: 1 if meses_rep[k] > 2 else 6)

    c["cod_empresa"] = c["empresa"].map(lambda e: EMPRESAS[e][0])
    circ = (c.groupby(["cod_empresa", "circuito"], as_index=False)
            .agg(primer_anio=("anio", "min"), ultimo_anio=("anio", "max")))
    circ.insert(0, "id_circuito", range(1, len(circ) + 1))
    circ["nombre"] = circ["circuito"].str.title()
    c = c.merge(circ[["id_circuito", "cod_empresa", "circuito"]], on=["cod_empresa", "circuito"])
    c["id_periodo"] = c["anio"] * 100 + c["mes"]
    fact = c[["id_periodo", "cod_empresa", "id_circuito", "tipo", "fpi", "dpir", "abonados", "fpi_x_abon",
              "dpir_x_abon", "meses"]]
    return fact, circ[["id_circuito", "cod_empresa", "circuito", "nombre", "primer_anio", "ultimo_anio"]]


def generacion() -> pd.DataFrame:
    g = leer_anios("generacion")
    g = g[g["empresaGenera"] == EMPRESAS["Coopelesca"][1]].drop_duplicates()
    g = g[g["planta"].isin(PLANTAS_COOPELESCA)]
    llave = ["anho", "id_Mes", "planta"]
    n = g.duplicated(llave).sum()
    if n:
        print(f"  generacion: {n} versiones distintas de la misma planta y mes, se conserva la ultima")
    g = g.drop_duplicates(llave, keep="last")
    g["kwh"] = g[["energiaPunta", "energiaValle", "energiaNoche"]].astype(float).sum(axis=1)
    g["id_periodo"] = g["anho"] * 100 + g["id_Mes"]
    g["planta"] = g["planta"].map(PLANTAS_COOPELESCA)
    return g[["id_periodo", "planta", "kwh"]].sort_values(["id_periodo", "planta"])


def lluvia(dist: pd.DataFrame) -> pd.DataFrame:
    pts = json.loads((RAW / "lluvia" / "puntos.json").read_text(encoding="utf-8"))
    om = json.loads((RAW / "lluvia" / "open_meteo.json").read_text(encoding="utf-8"))
    om = om if isinstance(om, list) else [om]
    rows = []
    for p, serie in zip(pts, om):
        d = pd.DataFrame({"fecha": pd.to_datetime(serie["daily"]["time"]),
                          "mm": serie["daily"]["precipitation_sum"]})
        m = d.groupby(d["fecha"].dt.year * 100 + d["fecha"].dt.month)["mm"].agg(["sum", "count"])
        for per, r in m.iterrows():
            rows.append({"cod_distrito": p["cod_distrito"], "id_periodo": per, "mm_era5": round(r["sum"], 1),
                         "dias": r["count"]})
    era5 = pd.DataFrame(rows)

    rows = []
    for p in pts:
        js = json.loads((RAW / "lluvia" / "nasa_power" / f"{p['cod_distrito']}.json").read_text(encoding="utf-8"))
        for k, v in js["properties"]["parameter"]["PRECTOTCORR_SUM"].items():
            if k.endswith("13") or v < 0:  # 13 = total anual; -999 = sin dato
                continue
            rows.append({"cod_distrito": p["cod_distrito"], "id_periodo": int(k), "mm_merra2": round(v, 1)})
    merra = pd.DataFrame(rows)
    out = era5.merge(merra, on=["cod_distrito", "id_periodo"], how="outer")
    assert set(out["cod_distrito"]) <= set(dist["cod_distrito"])
    return out[["cod_distrito", "id_periodo", "mm_era5", "mm_merra2"]]


def main():
    CLEAN.mkdir(parents=True, exist_ok=True)
    fact, circ = continuidad()
    gen = generacion()
    dist = distritos_concesion()
    llu = lluvia(dist)

    periodos = sorted(set(fact["id_periodo"]) | set(gen["id_periodo"]) | set(llu["id_periodo"]))
    dim_periodo = pd.DataFrame({"id_periodo": periodos})
    dim_periodo["anio"] = dim_periodo["id_periodo"] // 100
    dim_periodo["mes"] = dim_periodo["id_periodo"] % 100
    dim_periodo["nombre_mes"] = dim_periodo["mes"].map(lambda m: MESES[m - 1])
    dim_periodo["fecha"] = pd.to_datetime(dim_periodo["anio"].astype(str) + "-" +
                                          dim_periodo["mes"].astype(str) + "-01").dt.strftime("%Y-%m-%d")

    dim_empresa = pd.DataFrame([{"cod_empresa": v[0], "empresa": k, "razon_social": v[1]}
                                for k, v in EMPRESAS.items()])
    dim_tipo = pd.DataFrame(TIPOS, columns=["tipo", "nombre", "descripcion"])
    dim_distrito = dist.drop(columns="geometry").round({"pct_en_concesion": 4})
    dim_planta = pd.DataFrame({"planta": sorted(PLANTAS_COOPELESCA.values()), "cod_empresa": "COOPELESCA"})

    out = {"dim_periodo": dim_periodo, "dim_empresa": dim_empresa, "dim_tipo": dim_tipo,
           "dim_circuito": circ, "dim_distrito": dim_distrito, "dim_planta": dim_planta,
           "fact_continuidad": fact, "fact_lluvia": llu, "fact_generacion": gen}
    for name, df in out.items():
        df.to_csv(CLEAN / f"{name}.csv", index=False)
        print(f"  {name}: {len(df)} filas")


if __name__ == "__main__":
    main()
