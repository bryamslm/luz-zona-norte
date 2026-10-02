"""
Descarga las fuentes crudas a data/raw/.

    python scripts/descargar.py              # todo
    python scripts/descargar.py continuidad  # solo una fuente

Fuentes (todas publicas, sin clave):
- continuidad: ARESEP, datos abiertos "Indicadores de continuidad por empresa".
               FPI y DPIR por empresa, circuito, mes y tipo de indicador.
- generacion:  ARESEP, "Generacion por fuente, planta y capacidad instalada". Energia
               mensual por planta (kWh).
- concesion:   ARESEP, zonas de concesion de cada distribuidora (poligono CRTM05).
- limites:     IGN, limite distrital 1:5000 (WFS IGN_5_CO del SNIT).
- lluvia:      Open-Meteo (reanalisis ERA5) y NASA POWER (MERRA-2): lluvia en el
               centroide de cada distrito de la concesion de Coopelesca.

Cada descarga es idempotente: si el archivo ya existe, no se vuelve a bajar.
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "luz-zona-norte/0.1 (proyecto de portafolio; github.com/bryamslm/luz-zona-norte)"}

ARESEP = "https://datos.aresep.go.cr/ws.datosabiertos/Services/IE/Electricidad.svc"
IGN_WFS = "https://geos.snitcr.go.cr/be/IGN_5_CO/wfs"
OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
NASA_POWER = "https://power.larc.nasa.gov/api/temporal/monthly/point"

YEARS = range(2017, 2027)
LLUVIA_DESDE, LLUVIA_HASTA = 2019, 2025


def get(url: str, **kw) -> requests.Response:
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=180, **kw)
            if r.status_code < 500 and r.status_code != 429:
                return r
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    r.raise_for_status()
    return r


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def aresep_por_anio(endpoint: str, carpeta: str):
    """Un JSON por año. ARESEP responde 400 en los años que aun no publica."""
    for y in YEARS:
        out = RAW / carpeta / f"{y}.json"
        if out.exists():
            continue
        r = get(f"{ARESEP}/{endpoint}/{y}")
        rows = r.json().get("value") if r.status_code == 200 else None
        if not rows:  # 400 o "value": null -> el año no esta publicado
            print(f"  {carpeta} {y}: sin datos (HTTP {r.status_code})")
            continue
        save_json(out, r.json())
        print(f"  {carpeta} {y}: {len(rows)} filas")


def continuidad():
    aresep_por_anio("ObtenerIndicadoresContinuidadPorEmpresa", "continuidad")


def generacion():
    aresep_por_anio("ObtenerGeneracionFuentePlantaYCapacidadInstalada", "generacion")


def concesion():
    out = RAW / "concesion.json"
    if not out.exists():
        r = get(f"{ARESEP}/ObtenerInformacionZonasConcesionPorOperadorMapa")
        r.raise_for_status()
        save_json(out, r.json())
    print(f"  concesion: {out.stat().st_size // 1024} KB")


def limites():
    out = RAW / "limitedistrital_5k.geojson"
    if out.exists():
        return
    features, start = [], 0
    while True:
        r = get(IGN_WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                 "typeNames": "IGN_5_CO:limitedistrital_5k",
                                 "outputFormat": "application/json", "count": 500, "startIndex": start})
        r.raise_for_status()
        batch = r.json()["features"]
        features += batch
        if len(batch) < 500:
            break
        start += 500
    save_json(out, {"type": "FeatureCollection", "features": features})
    print(f"  limites: {len(features)} distritos")


def puntos_lluvia() -> list[dict]:
    """Centroide (WGS84) de cada distrito que cae en la concesion de Coopelesca."""
    from procesar import distritos_concesion
    d = distritos_concesion().to_crs(4326)
    return [{"cod_distrito": int(r.cod_distrito), "lat": round(r.geometry.centroid.y, 4),
             "lon": round(r.geometry.centroid.x, 4)} for r in d.itertuples()]


def lluvia():
    import warnings
    warnings.filterwarnings("ignore", message=".*geographic CRS.*")  # centroides de distritos: basta
    pts = puntos_lluvia()
    save_json(RAW / "lluvia" / "puntos.json", pts)

    out = RAW / "lluvia" / "open_meteo.json"
    if not out.exists():
        # una sola peticion con todas las coordenadas; respuesta: lista en el mismo orden
        r = get(OPEN_METEO, params={
            "latitude": ",".join(str(p["lat"]) for p in pts),
            "longitude": ",".join(str(p["lon"]) for p in pts),
            "start_date": f"{LLUVIA_DESDE}-01-01", "end_date": f"{LLUVIA_HASTA}-12-31",
            "daily": "precipitation_sum", "timezone": "America/Costa_Rica"})
        r.raise_for_status()
        save_json(out, r.json())
    print(f"  open-meteo: {len(pts)} puntos")

    for p in pts:
        out = RAW / "lluvia" / "nasa_power" / f"{p['cod_distrito']}.json"
        if out.exists():
            continue
        r = get(NASA_POWER, params={"parameters": "PRECTOTCORR_SUM", "community": "AG",
                                    "latitude": p["lat"], "longitude": p["lon"],
                                    "start": LLUVIA_DESDE, "end": LLUVIA_HASTA, "format": "JSON"})
        r.raise_for_status()
        save_json(out, r.json())
    print(f"  nasa power: {len(pts)} puntos")


SOURCES = {"continuidad": continuidad, "generacion": generacion, "concesion": concesion,
           "limites": limites, "lluvia": lluvia}

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for name in sys.argv[1:] or SOURCES:
        print(name)
        SOURCES[name]()
