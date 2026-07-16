import os
import re
import json
import subprocess
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from haversine import haversine, Unit
from datetime import datetime

FOLDERS = [
    "/mnt/common-hdd/raw-sources/twitter-data/raw-data/place_ids",
    "/mnt/common-hdd/raw-sources/twitter-data/raw-data/amsterdam/place_ids",
]
WORKERS = 16
OUTPUT_CSV = "../../tables/place.csv"
CWD = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================
# Step 1: Parse all place files in parallel
# ============================================

def process_file(path):
    result = subprocess.run(
        f"bash utils/place_json_filter.sh {path!r} | jq -c .",
        shell=True, capture_output=True, text=True, cwd=CWD
    )
    if result.returncode == 0 and result.stdout.strip():
        return ("ok", result.stdout.strip())
    return ("error", path)


all_files = []
for folder in FOLDERS:
    if os.path.isdir(folder):
        all_files += [os.path.join(folder, f) for f in os.listdir(folder)]

log(f"Processing {len(all_files):,} files with {WORKERS} workers...")

good, bad = [], []
with ProcessPoolExecutor(max_workers=WORKERS) as executor:
    futures = {executor.submit(process_file, p): p for p in all_files}
    for i, future in enumerate(as_completed(futures), 1):
        status, data = future.result()
        (good if status == "ok" else bad).append(data)
        if i % 2000 == 0:
            log(f"  {i:,}/{len(all_files):,} done ({len(good):,} ok, {len(bad):,} errors)")

log(f"Pass 1 done: {len(good):,} valid, {len(bad):,} errors")


# ============================================
# Step 2: Fix error files (True/False/nan)
# ============================================

def fix_and_parse(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    text = re.sub(r'("(?:[^"\\]|\\.)*?)\'((?:[^"\\]|\\.)*?")', r"\1\\'\2", text)
    text = re.sub(r'Place\(|BoundingBox\(', '{', text)
    text = text.replace(')', '}')
    text = re.sub(r'([{ ])([^={},]+?)=', r'\1"\2":', text)
    text = text.replace('<', '"').replace('>', '"')
    text = re.sub(r"([^\\])'", r'\1"', text)
    text = text.replace('None', 'null')
    text = text.replace("\\'", "'")
    text = re.sub(r'\bTrue\b', 'true', text)
    text = re.sub(r'\bFalse\b', 'false', text)
    text = re.sub(r'\bnan\b', 'null', text)
    try:
        obj = json.loads(text)
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None

fixed, still_broken = [], []
for path in bad:
    result = fix_and_parse(path)
    if result:
        fixed.append(result)
    else:
        still_broken.append(path)

log(f"Pass 2 done: {len(fixed):,} fixed, {len(still_broken):,} still broken")
if still_broken:
    log(f"Could not fix: {still_broken[:5]}")

all_lines = good + fixed
with open("places_all.json", "w") as f:
    f.write("\n".join(all_lines) + "\n")

log(f"places_all.json written: {len(all_lines):,} records")


# ============================================
# Step 3: Build place.csv
# ============================================

log("Building place.csv...")

with open("places_all.json") as f:
    df = pd.read_json(f, lines=True)

log(f"Loaded {df.shape[0]:,} rows")

df = df[df["bounding_box"].notnull()].copy()
df.drop_duplicates(subset=["id"], inplace=True)

df["lat_min"] = df["bounding_box"].map(lambda d: d["coordinates"][0][0][1])
df["lat_max"] = df["bounding_box"].map(lambda d: d["coordinates"][0][2][1])
df["lon_min"] = df["bounding_box"].map(lambda d: d["coordinates"][0][0][0])
df["lon_max"] = df["bounding_box"].map(lambda d: d["coordinates"][0][2][0])
df["centroid_lat"] = df["centroid"].map(lambda d: d[1])
df["centroid_lon"] = df["centroid"].map(lambda d: d[0])
df["err"] = df.apply(
    lambda row: haversine(
        (row["lat_min"], row["lon_min"]),
        (row["lat_max"], row["lon_max"]),
        unit=Unit.METERS
    ) / 2,
    axis=1
)

df = df[["id", "name", "full_name", "country_code", "place_type",
         "lon_min", "lon_max", "lat_min", "lat_max",
         "centroid_lon", "centroid_lat", "err"]].copy()

df.rename(columns={"id": "place_id", "name": "place_name"}, inplace=True)

os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_CSV)), exist_ok=True)
df.to_csv(OUTPUT_CSV, index=False, header=True)

log(f"Saved {df.shape[0]:,} places to {OUTPUT_CSV}")
log("Done")
