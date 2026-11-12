#!/usr/bin/env python3
"""Topic-specific robust distance diagnostics for the selected final model."""
import json
import numpy as np
import pandas as pd
from pipeline_config import *

FINAL = KMEANS_DIR / "final_model"


def main():
    k = int(FINAL_K)
    labels_path = FINAL / f"topics_k{k}.npy"
    distances_path = FINAL / f"assigned_centroid_distance_k{k}.npy"
    if not labels_path.exists() or not distances_path.exists():
        raise FileNotFoundError(
            "Canonical final labels/distances are missing. Run "
            "05_finalize_selected_model.py first; it is restart-safe and does not refit KMeans."
        )

    labels = np.load(labels_path, mmap_mode="r")
    distances = np.load(distances_path, mmap_mode="r")
    n = len(labels)
    if len(distances) != n:
        raise RuntimeError("Label/distance length mismatch.")

    med = np.empty(k)
    mad = np.empty(k)
    counts = np.bincount(np.asarray(labels), minlength=k)
    for t in range(k):
        d = np.asarray(distances[labels == t], dtype=np.float32)
        if len(d) == 0:
            raise RuntimeError(f"Empty topic {t}")
        med[t] = np.median(d)
        mad[t] = np.median(np.abs(d - med[t]))
        if mad[t] <= 0:
            raise RuntimeError(f"Non-positive MAD for topic {t}")

    zpath = FINAL / f"robust_z_k{k}.npy"
    z = np.lib.format.open_memmap(zpath, mode="w+", dtype=np.float32, shape=(n,))
    den = MAD_SCALE * mad
    for s in range(0, n, ASSIGN_CHUNK_SIZE):
        e = min(s + ASSIGN_CHUNK_SIZE, n)
        lab = np.asarray(labels[s:e], dtype=np.intp)
        z[s:e] = (
            (np.asarray(distances[s:e]) - med[lab]) / den[lab]
        ).astype(np.float32)
    z.flush()

    cutoff = float(np.quantile(np.asarray(z), LOW_CONFIDENCE_QUANTILE))
    lpath = FINAL / f"low_confidence_k{k}.npy"
    low = np.lib.format.open_memmap(lpath, mode="w+", dtype=np.bool_, shape=(n,))
    low[:] = np.asarray(z) >= cutoff
    low.flush()

    rows = []
    for t in range(k):
        m = labels == t
        d = np.asarray(distances[m])
        zz = np.asarray(z[m])
        ll = np.asarray(low[m])
        rows.append({
            "topic": t,
            "n_documents": int(counts[t]),
            "share": counts[t] / n,
            "median_assigned_distance": med[t],
            "mad_assigned_distance": mad[t],
            "mean_assigned_distance": float(d.mean()),
            "mean_robust_z": float(zz.mean()),
            "median_robust_z": float(np.median(zz)),
            "low_confidence_n": int(ll.sum()),
            "low_confidence_share": float(ll.mean()),
        })

    pd.DataFrame(rows).to_csv(
        FINAL / f"confidence_topic_summary_k{k}.csv", index=False
    )
    (FINAL / "confidence_metadata.json").write_text(
        json.dumps({
            "k": k,
            "fit_seed": int(FINAL_FIT_SEED),
            "mad_scale": MAD_SCALE,
            "low_confidence_quantile": LOW_CONFIDENCE_QUANTILE,
            "robust_z_cutoff": cutoff,
        }, indent=2),
        encoding="utf-8",
    )
    print("DONE")


if __name__ == "__main__":
    main()
