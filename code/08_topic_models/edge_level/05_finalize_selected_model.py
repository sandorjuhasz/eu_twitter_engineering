#!/usr/bin/env python3
"""Finalize the manually selected KMeans fit in a restart-safe way.

Works both after a clean step-04 run and after migration of existing results.
It never refits KMeans.

Accepted migrated fallbacks in final_model/:
    kmeans_model.pkl
    topics.npy

Canonical outputs:
    kmeans_k{K}_seed{SEED}.pkl
    topics_k{K}.npy
    assigned_centroid_distance_k{K}.npy
    topic_sizes_k{K}.csv
    final_model_metadata.json
"""
import json
import os
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from pipeline_config import *

X_PATH = SHARED_DIR / "umap_5d.npy"
SEL_DIR = KMEANS_DIR / "k_selection"
FINAL = KMEANS_DIR / "final_model"
FINAL.mkdir(parents=True, exist_ok=True)


def link_or_copy(src: Path, dst: Path):
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def find_model(k, seed):
    candidates = [
        SEL_DIR / f"kmeans_k{k}_seed{seed}.pkl",
        SEL_DIR / "models" / f"kmeans_k{k}_seed{seed}.pkl",
        FINAL / f"kmeans_k{k}_seed{seed}.pkl",
        FINAL / "kmeans_model.pkl",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Final KMeans model not found. Checked:\n" +
        "\n".join(f"  {p}" for p in candidates)
    )


def main():
    k = int(FINAL_K)
    seed = int(FINAL_FIT_SEED)
    x = np.load(X_PATH, mmap_mode="r")
    n = len(x)

    src_model = find_model(k, seed)
    model = joblib.load(src_model)
    if len(model.cluster_centers_) != k:
        raise RuntimeError(
            f"Model has {len(model.cluster_centers_)} centers, expected K={k}."
        )

    model_out = FINAL / f"kmeans_k{k}_seed{seed}.pkl"
    link_or_copy(src_model, model_out)

    labels_path = FINAL / f"topics_k{k}.npy"
    migrated_labels = FINAL / "topics.npy"

    # Reuse migrated exact labels if available; otherwise predict once.
    if not labels_path.exists() and migrated_labels.exists():
        lab0 = np.load(migrated_labels, mmap_mode="r")
        if lab0.ndim != 1 or len(lab0) != n:
            raise RuntimeError("Migrated topics.npy does not align with umap_5d.npy.")
        link_or_copy(migrated_labels, labels_path)

    if not labels_path.exists():
        labels = np.lib.format.open_memmap(
            labels_path, mode="w+", dtype=np.int16, shape=(n,)
        )
        for start in range(0, n, ASSIGN_CHUNK_SIZE):
            end = min(start + ASSIGN_CHUNK_SIZE, n)
            labels[start:end] = model.predict(
                np.asarray(x[start:end], dtype=np.float32)
            ).astype(np.int16)
            print(f"labels: {end:,}/{n:,}", flush=True)
        labels.flush()

    labels = np.load(labels_path, mmap_mode="r")
    if labels.ndim != 1 or len(labels) != n:
        raise RuntimeError("Final labels do not align with umap_5d.npy.")
    if int(labels.min()) < 0 or int(labels.max()) >= k:
        raise RuntimeError("Final labels contain values outside 0..K-1.")

    dist_path = FINAL / f"assigned_centroid_distance_k{k}.npy"
    sizes_path = FINAL / f"topic_sizes_k{k}.csv"

    # Distances are the only missing step after the current migration.
    # Compute them from the already-fixed labels and existing centroids.
    if not dist_path.exists():
        dist = np.lib.format.open_memmap(
            dist_path, mode="w+", dtype=np.float32, shape=(n,)
        )
        centers = np.asarray(model.cluster_centers_, dtype=np.float32)
        for start in range(0, n, ASSIGN_CHUNK_SIZE):
            end = min(start + ASSIGN_CHUNK_SIZE, n)
            chunk = np.asarray(x[start:end], dtype=np.float32)
            lab = np.asarray(labels[start:end], dtype=np.intp)
            delta = chunk - centers[lab]
            dist[start:end] = np.sqrt(
                np.einsum("ij,ij->i", delta, delta)
            ).astype(np.float32)
            print(f"distances: {end:,}/{n:,}", flush=True)
        dist.flush()

    distances = np.load(dist_path, mmap_mode="r")
    if distances.ndim != 1 or len(distances) != n:
        raise RuntimeError("Distance array does not align with final labels.")

    counts = np.bincount(np.asarray(labels), minlength=k)
    sums = np.bincount(
        np.asarray(labels),
        weights=np.asarray(distances, dtype=np.float64),
        minlength=k,
    )
    means = np.divide(
        sums, counts, out=np.full(k, np.nan), where=counts > 0
    )
    pd.DataFrame({
        "topic": np.arange(k),
        "n_documents": counts,
        "share": counts / n,
        "mean_assigned_distance": means,
    }).to_csv(sizes_path, index=False)

    meta = {
        "selection_mode": "manual",
        "selected_k": k,
        "selected_fit_seed": seed,
        "n_documents": n,
        "labels_path": str(labels_path),
        "distances_path": str(dist_path),
        "model_path": str(model_out),
        "source_fit_path": str(src_model),
        "restart_safe": True,
    }
    (FINAL / "final_model_metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"DONE: FINAL K={k}, seed={seed}")


if __name__ == "__main__":
    main()
