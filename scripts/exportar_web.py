"""
Exporta las series del analisis a web/datos.json para la pagina publica
luz.bryamlopez.com. Usa indicadores.py: las mismas reglas que las medidas DAX.

    python scripts/exportar_web.py
"""
import json
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicadores as ind  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
WEB = ROOT / "web"

MENSUALES = (2019, 2023, 2024)  # años en que Coopelesca reporto mes a mes
ATIPICO = (202309, "Marina")     # FPI 49 en un mes con 8.025 abonados: por verificar con la empresa
PLANTAS_FIJAS = ["Aguas Zarcas", "Chocosuelas", "La Esperanza"]  # completas desde 2019


def r(x, n=3):
    return None if pd.isna(x) else round(float(x), n)


def siguiente(p: int) -> int:
    return p + 1 if p % 100 < 12 else (p // 100 + 1) * 100 + 1


def main():
    f = ind.continuidad()
    lluvia = pd.read_csv(CLEAN / "fact_lluvia.csv")
    zona = lluvia.groupby("id_periodo")[["mm_era5", "mm_merra2"]].mean()

    # Empresas y pais ---------------------------------------------------------------------
    emp = ind.anual(f, ["anio", "cod_empresa"])
    nac = ind.anual(f, ["anio"])
    cols = ["fpi_1", "dpir_1", "fpi_ice", "fpi_externas", "fpi_internas"]
    empresas = [{"anio": int(x.anio), "empresa": x.cod_empresa, "abonados": round(x.abonados),
                 **{c: r(getattr(x, c)) for c in cols}} for x in emp.itertuples()]
    nacional = [{"anio": int(x.anio), "abonados": round(x.abonados), **{c: r(getattr(x, c)) for c in cols}}
                for x in nac.itertuples()]

    sin = f[~((f["id_periodo"] == ATIPICO[0]) & (f["nombre"] == ATIPICO[1]))]
    co23_sin = ind.anual(sin, ["anio", "cod_empresa"]).query("anio == 2023 and cod_empresa == 'COOPELESCA'").iloc[0]

    # Coopelesca mes a mes contra la lluvia -------------------------------------------------
    m = ind.mensual_empresa(f, "COOPELESCA").merge(zona, left_on="id_periodo", right_index=True)
    m = m[(m["id_periodo"] // 100).isin(MENSUALES)]
    mensual = [{"periodo": int(x.id_periodo), "fpi_total": r(x.fpi_total), "fpi_ice": r(x.fpi_ice),
                "fpi_externas": r(x.fpi_externas), "fpi_internas": r(x.fpi_internas), "mm": r(x.mm_era5, 0)}
               for x in m.itertuples()]
    x = m[m["id_periodo"] != ATIPICO[0]].copy()
    x["mes"] = x["id_periodo"] % 100
    rho, p = spearmanr(x["fpi_externas"], x["mm_era5"])
    prev = x.assign(mm_prev=x["id_periodo"].map({siguiente(k): v for k, v in zona["mm_era5"].items()}))
    prev = prev.dropna(subset=["mm_prev"])
    rho_lag, p_lag = spearmanr(prev["fpi_externas"], prev["mm_prev"])
    estac = x.groupby("mes")[["fpi_externas", "fpi_internas", "mm_era5"]].mean()
    x["epoca"] = x["mes"].map(lambda k: "seca" if k <= 4 else "lluviosa")  # IMN: lluvias de mayo a dic/ene
    epoca = x.groupby("epoca")[["fpi_externas", "fpi_internas", "mm_era5"]].mean()

    # Circuitos de Coopelesca, 2024 ---------------------------------------------------------
    co = f[f["cod_empresa"] == "COOPELESCA"]
    circ = ind.anual(co, ["anio", "cod_empresa", "nombre"]).query("anio == 2024")
    circ = circ.sort_values("fpi_1", ascending=False)
    # meses con FPI de un solo mes mayor que 10: atipicos que conviene mostrar aparte
    picos = (f[(f["tipo"] == 1) & (f["meses"] == 1) & (f["fpi"] > 10) & (f["cod_empresa"] == "COOPELESCA")]
             .sort_values("fpi", ascending=False))

    # Generacion contra lluvia ------------------------------------------------------------
    g = pd.read_csv(CLEAN / "fact_generacion.csv")
    gm = g.pivot_table(index="id_periodo", columns="planta", values="kwh", aggfunc="sum").div(1e6)
    gm = gm.join(zona["mm_era5"])
    tot = g.groupby("id_periodo")["kwh"].sum().div(1e6)
    d = pd.concat([tot.rename("gwh"), zona["mm_era5"]], axis=1).dropna()
    rho_g, p_g = spearmanr(d["gwh"], d["mm_era5"])
    fijas = (g[g["planta"].isin(PLANTAS_FIJAS)].assign(anio=g["id_periodo"] // 100)
             .groupby("anio")["kwh"].sum().div(1e6))
    anual_llu = zona["mm_era5"].groupby(zona.index // 100).sum()
    anual_merra = zona["mm_merra2"].groupby(zona.index // 100).sum()

    # Tablero: FPI de cada circuito en cada mes (años mensuales), filas por interrupciones del año
    tablero = {}
    for y in (2023, 2024):
        t = co[(co["anio"] == y) & (co["tipo"] == 1)]
        piv = t.pivot_table(index="nombre", columns=t["id_periodo"] % 100, values="fpi", aggfunc="sum")
        orden = t.groupby("nombre")["fpi_x_abon"].sum().sort_values(ascending=False).index
        piv = piv.reindex(orden)
        tablero[str(y)] = [{"circuito": n, "fpi": [r(v, 2) for v in fila]} for n, fila in piv.iterrows()]

    co_ult = emp.query("cod_empresa == 'COOPELESCA'").set_index("anio")
    datos = {
        "tablero": tablero,
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "resumen": {
            "anio": 2024,
            "fpi_coopelesca": r(co_ult.loc[2024, "fpi_1"], 2),
            "dpir_coopelesca": r(co_ult.loc[2024, "dpir_1"], 2),
            "pct_externas": r(co_ult.loc[2024, "fpi_externas"] / co_ult.loc[2024, "fpi_1"], 4),
            "fpi_internas": r(co_ult.loc[2024, "fpi_internas"], 2),
            "fpi_nacional": r(nac.set_index("anio").loc[2024, "fpi_1"], 2),
            "fpi_2023": r(co_ult.loc[2023, "fpi_1"], 2),
            "fpi_2023_sin_atipico": r(co23_sin["fpi_1"], 2),
            "abonados": round(co_ult.loc[2024, "abonados"]),
            "circuitos": int(circ["nombre"].nunique()),
        },
        "empresas": empresas,
        "nacional": nacional,
        "mensual": mensual,
        "estacionalidad": [{"mes": int(k), "fpi_externas": r(v.fpi_externas), "fpi_internas": r(v.fpi_internas),
                            "mm": r(v.mm_era5, 0)} for k, v in estac.iterrows()],
        "epoca": {k: {"fpi_externas": r(v.fpi_externas), "fpi_internas": r(v.fpi_internas), "mm": r(v.mm_era5, 0)}
                  for k, v in epoca.iterrows()},
        "correlacion": {"n": int(len(x)), "rho": r(rho), "p": r(p, 4), "rho_mes_anterior": r(rho_lag),
                        "p_mes_anterior": r(p_lag, 4), "rho_generacion": r(rho_g), "p_generacion": float(f"{p_g:.2e}"),
                        "n_generacion": int(len(d))},
        "circuitos_2024": [{"circuito": c.nombre, "fpi": r(c.fpi_1, 2), "dpir": r(c.dpir_1, 2),
                            "externas": r(c.fpi_externas, 2), "internas": r(c.fpi_internas, 2),
                            "abonados": round(c.abonados),
                            # interrupciones sufridas en total (abonado x vez): donde mas pesa el problema
                            "interrupciones": round(c.fpi_1 * c.abonados)} for c in circ.itertuples()],
        "atipicos": [{"periodo": int(a.id_periodo), "circuito": a.nombre, "fpi": r(a.fpi, 2), "dpir": r(a.dpir, 2),
                      "abonados": int(a.abonados)} for a in picos.itertuples()],
        "generacion": {
            "plantas": list(gm.columns.drop("mm_era5")),
            "mensual": [{"periodo": int(k), **{pl: r(v[pl], 2) for pl in gm.columns if pl != "mm_era5"},
                         "mm": r(v["mm_era5"], 0)} for k, v in gm.iterrows()],
            "anual_fijas": [{"anio": int(k), "gwh": r(v, 1), "mm": r(anual_llu.get(k), 0)}
                            for k, v in fijas.items() if k in anual_llu.index and (zona.index // 100 == k).sum() == 12],
        },
        "lluvia_fuentes": [{"anio": int(k), "era5": r(v, 0), "merra2": r(anual_merra.get(k), 0)}
                           for k, v in anual_llu.items()],
    }
    WEB.mkdir(exist_ok=True)
    (WEB / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"web/datos.json ({(WEB / 'datos.json').stat().st_size // 1024} KB)")
    print(json.dumps(datos["resumen"], ensure_ascii=False), json.dumps(datos["correlacion"]), sep="\n")


if __name__ == "__main__":
    main()
