#!/usr/bin/env python3
"""Reproducible K selection: full-corpus multiseed MiniBatchKMeans + matched silhouette samples.

Primary selection rule: choose K with the highest mean silhouette after first averaging the
10 matched silhouette samples within each fit seed, then averaging across the 10 fit seeds.
Inertia is reported as a diagnostic only and is not used to force an elbow.
The representative fit for the selected K is the seed whose fit-mean silhouette is closest
to that K's across-seed mean.
"""
import json, time
import joblib, numpy as np, pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score
from pipeline_config import *

X_PATH = SHARED_DIR / "umap_5d.npy"
OUT = KMEANS_DIR / "k_selection"; OUT.mkdir(exist_ok=True)
FIT_CSV = OUT / "fit_results.csv"; SIL_CSV = OUT / "silhouette_results.csv"


def model_path(k, seed): return OUT / f"kmeans_k{k}_seed{seed}.pkl"


def main():
    x = np.load(X_PATH, mmap_mode="r"); n = len(x)
    frows = pd.read_csv(FIT_CSV).to_dict("records") if FIT_CSV.exists() else []
    done = {(int(r["k"]), int(r["fit_seed"])) for r in frows}
    for k in K_VALUES:
        for seed in FIT_SEEDS:
            if (k, seed) in done and model_path(k, seed).exists(): continue
            print(f"FIT K={k} seed={seed}", flush=True)
            m = MiniBatchKMeans(n_clusters=k, batch_size=KMEANS_BATCH_SIZE, n_init=KMEANS_N_INIT,
                max_iter=KMEANS_MAX_ITER, reassignment_ratio=KMEANS_REASSIGNMENT_RATIO, random_state=seed)
            t = time.time(); m.fit(x); mins = (time.time()-t)/60; joblib.dump(m, model_path(k, seed))
            frows = [r for r in frows if not (int(r["k"])==k and int(r["fit_seed"])==seed)]
            frows.append({"k":k,"fit_seed":seed,"n_documents":n,"inertia":float(m.inertia_),
                          "inertia_per_document":float(m.inertia_/n),"fit_minutes":mins,
                          "model_path":str(model_path(k, seed))})
            pd.DataFrame(frows).sort_values(["k","fit_seed"]).to_csv(FIT_CSV,index=False)

    srows = pd.read_csv(SIL_CSV).to_dict("records") if SIL_CSV.exists() else []
    sdone = {(int(r["k"]),int(r["fit_seed"]),int(r["sample_rep"])) for r in srows}
    for rep in range(1, SILHOUETTE_REPS+1):
        sample_seed = SILHOUETTE_BASE_SEED + rep - 1
        rng = np.random.default_rng(sample_seed)
        idx = np.sort(rng.choice(n, size=min(SILHOUETTE_SAMPLE_N,n), replace=False))
        xs = np.asarray(x[idx], dtype=np.float32)
        for k in K_VALUES:
            for seed in FIT_SEEDS:
                if (k,seed,rep) in sdone: continue
                m = joblib.load(model_path(k,seed)); lab = m.predict(xs)
                t=time.time(); score=silhouette_score(xs,lab,metric="euclidean"); mins=(time.time()-t)/60
                srows.append({"k":k,"fit_seed":seed,"sample_rep":rep,"sample_seed":sample_seed,
                              "sample_n":len(xs),"silhouette":float(score),"silhouette_minutes":mins})
                pd.DataFrame(srows).sort_values(["k","fit_seed","sample_rep"]).to_csv(SIL_CSV,index=False)

    fdf=pd.read_csv(FIT_CSV); sdf=pd.read_csv(SIL_CSV)
    fitmeans=sdf.groupby(["k","fit_seed"],as_index=False).silhouette.mean().rename(columns={"silhouette":"fit_mean_silhouette"})
    summary=fitmeans.groupby("k").fit_mean_silhouette.agg(["mean","std","min","max"]).reset_index()
    summary=summary.rename(columns={"mean":"mean_silhouette","std":"sd_across_fit_seeds",
                                    "min":"min_fit_mean_silhouette","max":"max_fit_mean_silhouette"})
    inertia=fdf.groupby("k").inertia_per_document.agg(["mean","std","min","max"]).reset_index()
    inertia.columns=["k","mean_inertia_per_document","sd_inertia_per_document","min_inertia_per_document","max_inertia_per_document"]
    summary=summary.merge(inertia,on="k",how="left").sort_values("k")
    selected_k=int(summary.loc[summary.mean_silhouette.idxmax(),"k"])
    k_mean=float(summary.loc[summary.k==selected_k,"mean_silhouette"].iloc[0])
    cand=fitmeans[fitmeans.k==selected_k].copy(); cand["abs_distance_from_k_mean"]=(cand.fit_mean_silhouette-k_mean).abs()
    rep=cand.sort_values(["abs_distance_from_k_mean","fit_seed"]).iloc[0]
    selected_seed=int(rep.fit_seed)
    summary["selected_k"] = summary.k.eq(selected_k)
    summary.to_csv(OUT/"k_selection_summary.csv",index=False); fitmeans.to_csv(OUT/"fit_mean_silhouettes.csv",index=False)
    selection={"selection_metric":"mean silhouette across fit seeds; each fit mean uses matched silhouette samples",
               "selected_k":selected_k,"selected_representative_seed":selected_seed,
               "selected_k_mean_silhouette":k_mean,"representative_fit_mean_silhouette":float(rep.fit_mean_silhouette),
               "k_values":K_VALUES,"fit_seeds":FIT_SEEDS,"silhouette_reps":SILHOUETTE_REPS,
               "silhouette_sample_n":SILHOUETTE_SAMPLE_N,"inertia_role":"diagnostic only",
               "representative_fit_rule":"fit mean silhouette closest to selected K mean across fit seeds"}
    (OUT/"selected_model.json").write_text(json.dumps(selection,indent=2))
    print(json.dumps(selection,indent=2)); print("DONE")

if __name__ == "__main__": main()
