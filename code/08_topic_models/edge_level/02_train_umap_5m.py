#!/usr/bin/env python3
"""
Train UMAP on a deterministic 5,000,000-row sample of the existing full-corpus
384-dimensional embeddings.

This script does NOT regenerate embeddings and does NOT transform the full
31.4M corpus. It only trains UMAP and saves:
- the deterministic 5M sample indices;
- the fitted UMAP model;
- the 5M training coordinates;
- training metadata.

The full-corpus UMAP transform will be handled by a separate restartable script.
"""

import gc
import json
import pickle
import shutil
import time
from pathlib import Path

import numpy as np
from umap import UMAP

from pipeline_config import SHARED_DIR, UMAP_TRAIN_SIZE, UMAP_RANDOM_STATE, UMAP_N_NEIGHBORS, UMAP_N_COMPONENTS, UMAP_MIN_DIST, UMAP_METRIC

OUTPUT_DIR = SHARED_DIR

EMBEDDINGS_PATH = OUTPUT_DIR / "embeddings_384d.npy"
COUNT_PATH = OUTPUT_DIR / "n_documents.txt"

TRAIN_SIZE = UMAP_TRAIN_SIZE
RANDOM_STATE = UMAP_RANDOM_STATE
N_NEIGHBORS = UMAP_N_NEIGHBORS
N_COMPONENTS = UMAP_N_COMPONENTS
MIN_DIST = UMAP_MIN_DIST
METRIC = UMAP_METRIC

SAMPLE_INDICES_PATH = OUTPUT_DIR / "umap_train_5m_indices.npy"
MODEL_PATH = OUTPUT_DIR / "umap_model_train_5m.pkl"
TRAIN_COORDS_PATH = OUTPUT_DIR / "umap_train_5m_coordinates.npy"
METADATA_PATH = OUTPUT_DIR / "umap_train_5m_metadata.json"


def gib(n_bytes):
    return n_bytes / (1024 ** 3)


def available_ram_bytes():
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def resource_status(label):
    disk = shutil.disk_usage(OUTPUT_DIR)
    ram = available_ram_bytes()
    ram_text = f"{gib(ram):.1f} GiB" if ram is not None else "unknown"
    print(
        f"[{label}] available RAM={ram_text}; "
        f"disk free={gib(disk.free):.1f} GiB / total={gib(disk.total):.1f} GiB",
        flush=True,
    )


def load_embeddings():
    if not EMBEDDINGS_PATH.exists():
        raise FileNotFoundError(f"Missing embedding cache: {EMBEDDINGS_PATH}")

    embeddings = np.load(EMBEDDINGS_PATH, mmap_mode="r")

    if embeddings.ndim != 2 or embeddings.shape[1] != 384:
        raise RuntimeError(
            f"Unexpected embedding shape {embeddings.shape}; expected (N, 384)."
        )

    if COUNT_PATH.exists():
        expected_n = int(COUNT_PATH.read_text().strip())
        if embeddings.shape[0] != expected_n:
            raise RuntimeError(
                f"Embedding rows={embeddings.shape[0]:,}, "
                f"n_documents.txt={expected_n:,}."
            )

    return embeddings


def get_sample_indices(n_docs):
    sample_size = min(TRAIN_SIZE, n_docs)

    if SAMPLE_INDICES_PATH.exists():
        indices = np.load(SAMPLE_INDICES_PATH)
        if len(indices) != sample_size:
            raise RuntimeError(
                f"Cached sample has {len(indices):,} rows; expected {sample_size:,}."
            )
        print(f"Using cached sample indices: {SAMPLE_INDICES_PATH}", flush=True)
        return indices

    print(
        f"Drawing deterministic sample: {sample_size:,} / {n_docs:,}",
        flush=True,
    )

    rng = np.random.default_rng(RANDOM_STATE)
    indices = rng.choice(n_docs, size=sample_size, replace=False)

    # Sorting preserves the sampled set and makes memmap access more sequential.
    indices.sort()
    np.save(SAMPLE_INDICES_PATH, indices)

    print(f"Saved sample indices: {SAMPLE_INDICES_PATH}", flush=True)
    return indices


def materialize_sample(embeddings, indices):
    raw_bytes = len(indices) * embeddings.shape[1] * np.dtype(np.float32).itemsize
    print(
        f"Materializing training sample in RAM: ~{gib(raw_bytes):.1f} GiB raw float32",
        flush=True,
    )

    start = time.time()
    sample = np.asarray(embeddings[indices], dtype=np.float32)

    print(
        f"Sample ready in {(time.time() - start) / 60:.2f} min; "
        f"shape={sample.shape}",
        flush=True,
    )
    resource_status("SAMPLE READY")
    return sample


def fit_umap(sample, n_docs):
    if MODEL_PATH.exists() and TRAIN_COORDS_PATH.exists():
        coords = np.load(TRAIN_COORDS_PATH, mmap_mode="r")
        expected_shape = (len(sample), N_COMPONENTS)
        if coords.shape == expected_shape:
            print("UMAP model and 5M coordinates already exist; skipping fit.", flush=True)
            return
        raise RuntimeError(
            f"Unexpected cached training-coordinate shape: {coords.shape}"
        )

    reducer = UMAP(
        n_neighbors=N_NEIGHBORS,
        n_components=N_COMPONENTS,
        min_dist=MIN_DIST,
        metric=METRIC,
        random_state=RANDOM_STATE,
        low_memory=True,
        verbose=True,
    )

    print("\n" + "=" * 88, flush=True)
    print("FITTING UMAP ON 5,000,000 EMBEDDINGS", flush=True)
    print("=" * 88, flush=True)
    resource_status("UMAP FIT START")

    start = time.time()
    reduced = reducer.fit_transform(sample).astype(np.float32, copy=False)
    fit_minutes = (time.time() - start) / 60

    print(f"UMAP fit completed in {fit_minutes:.2f} min.", flush=True)
    resource_status("UMAP FIT END")

    np.save(TRAIN_COORDS_PATH, reduced)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(reducer, f, protocol=pickle.HIGHEST_PROTOCOL)

    metadata = {
        "full_n_documents": int(n_docs),
        "training_n_documents": int(len(sample)),
        "embedding_path": str(EMBEDDINGS_PATH),
        "sample_indices_path": str(SAMPLE_INDICES_PATH),
        "model_path": str(MODEL_PATH),
        "training_coordinates_path": str(TRAIN_COORDS_PATH),
        "random_state": RANDOM_STATE,
        "n_neighbors": N_NEIGHBORS,
        "n_components": N_COMPONENTS,
        "min_dist": MIN_DIST,
        "metric": METRIC,
        "low_memory": True,
        "fit_minutes": fit_minutes,
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2))

    print(f"Saved UMAP model: {MODEL_PATH}", flush=True)
    print(f"Saved training coordinates: {TRAIN_COORDS_PATH}", flush=True)
    print(f"Saved metadata: {METADATA_PATH}", flush=True)

    del reduced
    del reducer
    gc.collect()


def main():
    print("=" * 88, flush=True)
    print("UMAP TRAINING ON 5M EMBEDDING SAMPLE", flush=True)
    print("=" * 88, flush=True)
    print(f"Embeddings: {EMBEDDINGS_PATH}", flush=True)
    print(f"Output: {OUTPUT_DIR}", flush=True)
    resource_status("START")

    embeddings = load_embeddings()
    n_docs = embeddings.shape[0]

    print(f"Full embedding matrix: {embeddings.shape}", flush=True)
    print(f"Training sample size: {min(TRAIN_SIZE, n_docs):,}", flush=True)

    indices = get_sample_indices(n_docs)
    sample = materialize_sample(embeddings, indices)
    fit_umap(sample, n_docs)

    del sample
    del indices
    del embeddings
    gc.collect()

    resource_status("END")
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
