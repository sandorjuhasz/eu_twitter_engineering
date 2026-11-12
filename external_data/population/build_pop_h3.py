"""Aggregate GHS-POP R2023A (epoch 2015, 100 m, Mollweide) to H3 cells (res 8/9/10)
for the London, Portland and Amsterdam city bounding boxes.

Output: pop_h3.csv with columns city, res, cell, pop.
Re-runnable: downloads the two required GHSL tiles into raw/ if missing.
"""
import os
import urllib.request
import zipfile

import h3
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "pop_h3.csv")

BASE_URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
            "GHS_POP_E2015_GLOBE_R2023A_54009_100/V1-0/tiles/")
TILE_NAME = "GHS_POP_E2015_GLOBE_R2023A_54009_100_V1_0_{}"

# city: (lat_min, lat_max, lon_min, lon_max, GHSL tile)
BOXES = {
    "london": (51.2867601, 51.6918741, -0.5103751, 0.3340155, "R3_C19"),
    "portland": (45.4325360, 45.6528812, -122.8367489, -122.4720252, "R4_C9"),
    "amsterdam": (52.2781742, 52.4310638, 4.7287776, 5.0791622, "R3_C19"),
}
RESOLUTIONS = [8, 9, 10]
MARGIN_M = 3000  # clip margin around the box, so edge cells get all their pixels


def get_tile(tile):
    tif = os.path.join(RAW, TILE_NAME.format(tile) + ".tif")
    if not os.path.exists(tif):
        os.makedirs(RAW, exist_ok=True)
        zpath = os.path.join(RAW, TILE_NAME.format(tile) + ".zip")
        urllib.request.urlretrieve(BASE_URL + TILE_NAME.format(tile) + ".zip", zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(RAW)
    return tif


def pixels_in_box(tif, lat_min, lat_max, lon_min, lon_max):
    """Return lat, lon of pixel centroids and their population for the box + margin."""
    with rasterio.open(tif) as src:
        to_moll = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        lons = np.linspace(lon_min, lon_max, 50)
        lats = np.linspace(lat_min, lat_max, 50)
        glon, glat = np.meshgrid(lons, lats)
        x, y = to_moll.transform(glon.ravel(), glat.ravel())
        win = from_bounds(x.min() - MARGIN_M, y.min() - MARGIN_M,
                          x.max() + MARGIN_M, y.max() + MARGIN_M, src.transform)
        win = win.round_offsets().round_lengths()
        arr = src.read(1, window=win)
        tr = src.window_transform(win)
        nodata = src.nodata
        crs = src.crs
    rows, cols = np.nonzero((arr > 0) & (arr != nodata))
    pop = arr[rows, cols].astype(float)
    xs = tr.c + (cols + 0.5) * tr.a
    ys = tr.f + (rows + 0.5) * tr.e
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon, lat = to_wgs.transform(xs, ys)
    return lat, lon, pop


def main():
    frames = []
    for city, (lat_min, lat_max, lon_min, lon_max, tile) in BOXES.items():
        lat, lon, pop = pixels_in_box(get_tile(tile), lat_min, lat_max, lon_min, lon_max)
        for res in RESOLUTIONS:
            cells = [h3.latlng_to_cell(a, b, res) for a, b in zip(lat, lon)]
            df = (pd.DataFrame({"cell": cells, "pop": pop})
                  .groupby("cell", as_index=False)["pop"].sum())
            centres = np.array([h3.cell_to_latlng(c) for c in df["cell"]])
            inside = ((centres[:, 0] >= lat_min) & (centres[:, 0] <= lat_max)
                      & (centres[:, 1] >= lon_min) & (centres[:, 1] <= lon_max))
            df = df[inside & (df["pop"] > 0)]
            df.insert(0, "res", res)
            df.insert(0, "city", city)
            frames.append(df)
            print(f"{city:10s} res {res:2d}: {len(df):6d} cells, pop {df['pop'].sum():12,.0f}")
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(OUT, index=False, float_format="%.4f")
    print("wrote", OUT, len(out), "rows")


if __name__ == "__main__":
    main()
