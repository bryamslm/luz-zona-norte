"""
Carga data/clean/*.csv en SQL Server (esquema dw) y verifica contra cifras publicadas.

    ssh -f -N -L 14333:127.0.0.1:14333 bryam   # tunel; SQL Server solo escucha en localhost
    python scripts/cargar.py

Credenciales en .env (no versionado). La primera corrida crea la base y los logins
luz_etl (carga) y luz_bi (solo lectura, para Power BI).
"""
import re
from pathlib import Path

import pandas as pd
import pymssql

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"

# Orden de carga: dimensiones antes que hechos por las llaves foraneas.
TABLES = ["dim_periodo", "dim_empresa", "dim_tipo", "dim_circuito", "dim_distrito", "dim_planta",
          "fact_continuidad", "fact_lluvia", "fact_generacion"]

# (descripcion, consulta, valor publicado, tolerancia relativa)
CONTROLES = [
    ("FPI nacional 2024 (ARESEP: 7,63)",
     "select sum(fpi_total * abonados) / sum(abonados) from dw.v_continuidad_empresa_anual where anio = 2024",
     7.63, 0.02),
    ("DPIR nacional 2022 (ARESEP: 8 h 22 min)",
     "select sum(dpir_total * abonados) / sum(abonados) from dw.v_continuidad_empresa_anual where anio = 2022",
     8 + 22 / 60, 0.05),
    ("Lluvia media anual de la zona, ERA5 (IMN Zona Norte: 3.172 ± 659 mm)",
     "select avg(mm) from (select left(id_periodo, 4) a, sum(mm_era5) mm from dw.v_lluvia_zona "
     "where id_periodo < 202600 group by left(id_periodo, 4)) t",
     3172, 659 / 3172 * 1.5),
]


def env() -> dict:
    return dict(l.strip().split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l)


def connect(e: dict, user: str, password: str, database: str = "master"):
    return pymssql.connect(server=e["MSSQL_HOST"], port=e["MSSQL_PORT"], user=user,
                           password=password, database=database, autocommit=True)


def ensure_database(e: dict):
    """Base y logins. Idempotente: no toca lo que ya existe."""
    with connect(e, "sa", e["MSSQL_SA_PASSWORD"]) as conn, conn.cursor() as cur:
        db = e["MSSQL_DB"]
        cur.execute(f"if db_id('{db}') is null create database {db}")
        for login, key in (("luz_etl", "MSSQL_ETL_PASSWORD"), ("luz_bi", "MSSQL_BI_PASSWORD")):
            pw = e[key].replace("'", "''")
            cur.execute(f"if suser_id('{login}') is null create login {login} with password = '{pw}', check_policy = off")
            cur.execute(f"use {db}; if user_id('{login}') is null create user {login} for login {login}")
        cur.execute(f"use {db}; alter role db_owner add member luz_etl")


def main():
    e = env()
    ensure_database(e)
    with connect(e, "luz_etl", e["MSSQL_ETL_PASSWORD"], e["MSSQL_DB"]) as conn, conn.cursor() as cur:
        script = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
        for batch in re.split(r"^\s*GO\s*$", script, flags=re.MULTILINE):
            if batch.strip():
                cur.execute(batch)

        for table in TABLES:
            df = pd.read_csv(CLEAN / f"{table}.csv")
            cols = ", ".join(df.columns)
            row_marks = "(" + ", ".join(["%s"] * len(df.columns)) + ")"
            rows = [tuple(None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r)
                    for r in df.itertuples(index=False)]
            # un INSERT acepta hasta 1000 filas y 2100 parametros: se agrupa respetando ambos topes
            chunk = min(1000, 2000 // len(df.columns))
            for i in range(0, len(rows), chunk):
                part = rows[i:i + chunk]
                cur.execute(f"insert into dw.{table} ({cols}) values " + ", ".join([row_marks] * len(part)),
                            tuple(v for r in part for v in r))
            print(f"dw.{table}: {len(df)} filas")

        fallas = 0
        for label, sql, publicado, tol in CONTROLES:
            cur.execute(sql)
            v = float(cur.fetchone()[0])
            ok = abs(v / publicado - 1) <= tol
            fallas += not ok
            print(f"control {'OK ' if ok else 'FALLA'} {label}: {v:,.2f} ({v / publicado - 1:+.1%})")
        if fallas:
            raise SystemExit(f"{fallas} controles fuera de tolerancia")


if __name__ == "__main__":
    main()
