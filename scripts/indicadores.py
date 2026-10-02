"""
Las mismas reglas que las medidas DAX, en pandas. Las usan cargar.py (controles) y
exportar_web.py (pagina publica), para que las tres salidas den los mismos numeros.

FPI de un grupo (empresa, pais, circuito) en un año:
    sum(fpi * abonados) de todas sus filas  /  abonados promedio de sus periodos reportados
Asi una empresa semestral (2 filas al año) y una mensual (12) se miden igual, y un circuito
recien energizado con 57 abonados no pesa como uno de 8.000.
"""
from pathlib import Path

import pandas as pd

CLEAN = Path(__file__).resolve().parent.parent / "data" / "clean"


def continuidad() -> pd.DataFrame:
    f = pd.read_csv(CLEAN / "fact_continuidad.csv")
    c = pd.read_csv(CLEAN / "dim_circuito.csv")
    f = f.merge(c[["id_circuito", "nombre"]], on="id_circuito")
    f["anio"] = f["id_periodo"] // 100
    return f


def anual(f: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    """FPI y DPIR anuales por tipo, agrupando por `por` (siempre incluye anio y empresa)."""
    base = ["anio", "cod_empresa"]
    ab = (f[f["tipo"] == 1].groupby(base + [c for c in por if c not in base] + ["id_periodo"])["abonados"].sum()
          .groupby(level=list(range(len(base) + len([c for c in por if c not in base])))).mean()
          .rename("abonados"))
    keys = base + [c for c in por if c not in base]
    s = f.groupby(keys + ["tipo"])[["fpi_x_abon", "dpir_x_abon"]].sum().unstack("tipo")
    out = pd.DataFrame(index=s.index)
    out = out.join(ab)
    for t in (1, 2, 3):
        out[f"fpi_{t}"] = s[("fpi_x_abon", t)] / out["abonados"]
        out[f"dpir_{t}"] = s[("dpir_x_abon", t)] / out["abonados"]
    # descomposicion por causa (definiciones de la plantilla PCE 05 de ARESEP)
    out["fpi_ice"] = out["fpi_1"] - out["fpi_2"]
    out["fpi_externas"] = out["fpi_2"] - out["fpi_3"]
    out["fpi_internas"] = out["fpi_3"]
    out = out.reset_index()
    if "cod_empresa" not in por:  # agregado de varias empresas: promedio ponderado por abonados
        num = out.assign(**{k: out[k] * out["abonados"] for k in out if k.startswith(("fpi", "dpir"))})
        g = num.groupby([k for k in keys if k != "cod_empresa"])
        out = g[[k for k in out if k.startswith(("fpi", "dpir"))]].sum().div(g["abonados"].sum(), axis=0)
        out["abonados"] = g["abonados"].sum()
        out = out.reset_index()
    return out


def mensual_empresa(f: pd.DataFrame, empresa: str) -> pd.DataFrame:
    """FPI de cada mes para una empresa que reporta mensualmente."""
    e = f[f["cod_empresa"] == empresa]
    s = e.groupby(["id_periodo", "tipo"])[["fpi_x_abon", "abonados"]].sum()
    m = (s["fpi_x_abon"] / s["abonados"]).unstack("tipo")
    return pd.DataFrame({"fpi_total": m[1], "fpi_ice": m[1] - m[2], "fpi_externas": m[2] - m[3],
                         "fpi_internas": m[3]}).reset_index()
