#!/usr/bin/env python3
"""Select core/typical/periphery examples for every topic in the selected final model."""
import json
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from pipeline_config import *
FINAL=KMEANS_DIR/"final_model"

def db_engine():
    with open(CONNECTION_PATH,encoding="utf-8") as f:c=json.load(f)
    return create_engine(URL.create("postgresql+psycopg2",username=c["user"],password=c["password"],host=c["host"],port=c["port"],database=c["database"]),pool_pre_ping=True)

def main():
    k=int(FINAL_K); labels_path=FINAL/f"topics_k{k}.npy"; dist_path=FINAL/f"assigned_centroid_distance_k{k}.npy"
    if not labels_path.exists() or not dist_path.exists(): raise FileNotFoundError("Run 05_finalize_selected_model.py first.")
    labels=np.load(labels_path,mmap_mode="r"); dist=np.load(dist_path,mmap_mode="r"); n=len(labels)
    rows=[]
    for t in range(k):
        idx=np.flatnonzero(labels==t); d=np.asarray(dist[idx]); median=float(np.median(d))
        for band,q in EXAMPLE_QUANTILES.items():
            target=float(np.quantile(d,q)); order=np.argsort(np.abs(d-target))[:N_EXAMPLES_PER_BAND]
            for rank,pos in enumerate(order,1): rows.append({"topic":t,"band":band,"rank":rank,"global_row":int(idx[pos]),"distance":float(d[pos]),"normalized_distance":float(d[pos]/median)})
    sdf=pd.DataFrame(rows); wanted=np.sort(sdf.global_row.unique()); texts={}; ptr=0; row=0; eng=db_engine(); q=text(f"SELECT {TEXT_COLUMN} FROM {SOURCE_TABLE} WHERE {TEXT_COLUMN} IS NOT NULL AND n_cleaned_words >= {MIN_CLEANED_WORDS} ORDER BY {', '.join(ORDER_COLS)}")
    with eng.connect().execution_options(stream_results=True) as conn:
        res=conn.execute(q)
        while True:
            rec=res.fetchmany(REPRESENTATION_FETCH_SIZE)
            if not rec: break
            end=row+len(rec)
            while ptr<len(wanted) and wanted[ptr]<end:
                texts[int(wanted[ptr])]=str(rec[int(wanted[ptr]-row)][0]); ptr+=1
            row=end
    eng.dispose()
    if row!=n or ptr!=len(wanted): raise RuntimeError("DB/label alignment failure")
    sdf["text"]=sdf.global_row.map(texts); sdf.to_csv(FINAL/f"core_typical_periphery_examples_k{k}.csv",index=False)
    print(f"K={k}; topics={k}; example slots={len(sdf):,}; unique documents={len(wanted):,}")
if __name__=="__main__": main()
