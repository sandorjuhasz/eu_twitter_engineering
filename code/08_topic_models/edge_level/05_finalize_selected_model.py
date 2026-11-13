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

    # Existing or migrated labels are accepted only after checking every row
    # against the selected fitted model and the current UMAP coordinates.
    candidate = labels_path if labels_path.exists() else (migrated_labels if migrated_labels.exists() else None)
    if candidate is not None:
        existing = np.load(candidate, mmap_mode="r")
        if existing.ndim != 1 or len(existing) != n:
            raise RuntimeError(f"Existing labels do not align with umap_5d.npy: {candidate}")
        for start in range(0, n, ASSIGN_CHUNK_SIZE):
            end = min(start + ASSIGN_CHUNK_SIZE, n)
            predicted = model.predict(np.asarray(x[start:end], dtype=np.float32))
            if not np.array_equal(existing[start:end], predicted):
                raise RuntimeError(f"Existing labels disagree with selected model at rows {start:,}:{end:,}: {candidate}")
        if candidate == migrated_labels:
            link_or_copy(migrated_labels, labels_path)

    if not labels_path.exists():
        labels_tmp = labels_path.with_suffix(".npy.tmp")
        labels = np.lib.format.open_memmap(
            labels_tmp, mode="w+", dtype=np.int16, shape=(n,)
        )
        for start in range(0, n, ASSIGN_CHUNK_SIZE):
            end = min(start + ASSIGN_CHUNK_SIZE, n)
            labels[start:end] = model.predict(
                np.asarray(x[start:end], dtype=np.float32)
            ).astype(np.int16)
            print(f"labels: {end:,}/{n:,}", flush=True)
        labels.flush()
        del labels
        os.replace(labels_tmp, labels_path)

    labels = np.load(labels_path, mmap_mode="r")
    if labels.ndim != 1 or len(labels) != n:
        raise RuntimeError("Final labels do not align with umap_5d.npy.")
    if int(labels.min()) < 0 or int(labels.max()) >= k:
        raise RuntimeError("Final labels contain values outside 0..K-1.")

    dist_path = FINAL / f"assigned_centroid_distance_k{k}.npy"
    sizes_path = FINAL / f"topic_sizes_k{k}.csv"

    # Recompute distances into a temporary file, then replace atomically.
    # Reuse only when a previous completed final-model metadata file exists.
    if not dist_path.exists() or not (FINAL / "final_model_metadata.json").exists():
        dist_tmp = dist_path.with_suffix(".npy.tmp")
        dist = np.lib.format.open_memmap(
            dist_tmp, mode="w+", dtype=np.float32, shape=(n,)
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
        del dist
        os.replace(dist_tmp, dist_path)

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
