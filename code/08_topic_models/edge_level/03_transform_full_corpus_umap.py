#!/usr/bin/env python3
"""Restartable full-corpus transform with the fitted 5M UMAP model."""

import gc
import json
import pickle
import shutil
import time
from pathlib import Path

import numpy as np

from pipeline_config import SHARED_DIR, UMAP_N_COMPONENTS, UMAP_TRANSFORM_CHUNK

OUTPUT_DIR = SHARED_DIR
EMBEDDINGS_PATH = OUTPUT_DIR / "embeddings_384d.npy"
UMAP_MODEL_PATH = OUTPUT_DIR / "umap_model_train_5m.pkl"
UMAP_OUTPUT_PATH = OUTPUT_DIR / "umap_5d.npy"
PROGRESS_PATH = OUTPUT_DIR / "umap_transform_progress.json"
METADATA_PATH = OUTPUT_DIR / "umap_transform_metadata.json"

N_COMPONENTS = UMAP_N_COMPONENTS
CHUNK_SIZE = UMAP_TRANSFORM_CHUNK


def gib(n):
    return n / (1024 ** 3)


def available_ram_bytes():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    return None


def resources(label):
    disk = shutil.disk_usage(OUTPUT_DIR)
    ram = available_ram_bytes()
    ram_text = f"{gib(ram):.1f} GiB" if ram else "unknown"
    print(
        f"[{label}] available RAM={ram_text}; "
        f"disk free={gib(disk.free):.1f} GiB / total={gib(disk.total):.1f} GiB",
        flush=True,
    )


def load_inputs():
    if not EMBEDDINGS_PATH.exists():
        raise FileNotFoundError(EMBEDDINGS_PATH)
    if not UMAP_MODEL_PATH.exists():
        raise FileNotFoundError(UMAP_MODEL_PATH)

    embeddings = np.load(EMBEDDINGS_PATH, mmap_mode="r")
    if embeddings.ndim != 2 or embeddings.shape[1] != 384:
        raise RuntimeError(f"Unexpected embedding shape: {embeddings.shape}")

    print(f"Loading fitted UMAP model: {UMAP_MODEL_PATH}", flush=True)
    t0 = time.time()
    with open(UMAP_MODEL_PATH, "rb") as f:
        reducer = pickle.load(f)
    print(f"Model loaded in {(time.time()-t0)/60:.2f} min.", flush=True)

    if reducer.n_components != N_COMPONENTS:
        raise RuntimeError(f"UMAP n_components={reducer.n_components}, expected 5")

    return embeddings, reducer


def open_output(n_docs):
    expected = (n_docs, N_COMPONENTS)

    if UMAP_OUTPUT_PATH.exists():
        output = np.lib.format.open_memmap(UMAP_OUTPUT_PATH, mode="r+")
        if output.shape != expected:
            raise RuntimeError(f"Existing output shape {output.shape}, expected {expected}")

        if not PROGRESS_PATH.exists():
            print("umap_5d.npy already complete; nothing to do.", flush=True)
            return output, n_docs

        progress = json.loads(PROGRESS_PATH.read_text())
        start_row = int(progress["completed_rows"])
        print(f"Resuming at row {start_row:,}.", flush=True)
        return output, start_row

    if PROGRESS_PATH.exists():
        raise RuntimeError("Progress file exists but umap_5d.npy is missing.")

    output = np.lib.format.open_memmap(
        UMAP_OUTPUT_PATH,
        mode="w+",
        dtype=np.float32,
        shape=expected,
    )
    output.flush()
    PROGRESS_PATH.write_text(json.dumps({
        "completed_rows": 0,
        "n_documents": n_docs,
        "chunk_size": CHUNK_SIZE,
    }, indent=2))
    return output, 0


def transform_all(embeddings, reducer, output, start_row):
    n_docs = embeddings.shape[0]
    if start_row == n_docs:
        return

    session_start = time.time()
    session_start_row = start_row
    row = start_row
    total_chunks = (n_docs + CHUNK_SIZE - 1) // CHUNK_SIZE

    while row < n_docs:
        chunk_no = row // CHUNK_SIZE + 1
        end = min(row + CHUNK_SIZE, n_docs)
        t0 = time.time()

        x = np.asarray(embeddings[row:end], dtype=np.float32)
        y = reducer.transform(x).astype(np.float32, copy=False)
        output[row:end] = y
        output.flush()
        row = end

        elapsed = max(time.time() - session_start, 1e-9)
        rate = (row - session_start_row) / elapsed
        eta_h = (n_docs - row) / rate / 3600 if rate > 0 else float("nan")
        chunk_min = (time.time() - t0) / 60
        ram = available_ram_bytes()
        ram_text = f"{gib(ram):.1f} GiB" if ram else "unknown"

        PROGRESS_PATH.write_text(json.dumps({
            "completed_rows": row,
            "n_documents": n_docs,
            "chunk_size": CHUNK_SIZE,
            "completed_fraction": row / n_docs,
            "session_docs_per_second": rate,
            "eta_hours": eta_h,
        }, indent=2))

        print(
            f"Chunk {chunk_no:,}/{total_chunks:,}: "
            f"{row:,}/{n_docs:,} ({row/n_docs:.2%}); "
            f"chunk={chunk_min:.2f} min; rate={rate:.1f} docs/s; "
            f"ETA={eta_h:.1f} h; available RAM={ram_text}",
            flush=True,
        )

        del x, y
        if chunk_no % 10 == 0:
            gc.collect()

    output.flush()
    METADATA_PATH.write_text(json.dumps({
        "n_documents": n_docs,
        "embedding_dimensions": embeddings.shape[1],
        "umap_dimensions": N_COMPONENTS,
        "chunk_size": CHUNK_SIZE,
        "embedding_path": str(EMBEDDINGS_PATH),
        "umap_model_path": str(UMAP_MODEL_PATH),
        "output_path": str(UMAP_OUTPUT_PATH),
    }, indent=2))
    PROGRESS_PATH.unlink(missing_ok=True)
    print(f"Full transform complete: {UMAP_OUTPUT_PATH}", flush=True)


def main():
    print("=" * 88, flush=True)
    print("FULL-CORPUS UMAP TRANSFORM", flush=True)
    print("=" * 88, flush=True)
    print(f"Chunk size: {CHUNK_SIZE:,}", flush=True)
    resources("START")

    embeddings, reducer = load_inputs()
    print(f"Embedding matrix: {embeddings.shape}", flush=True)

    output, start_row = open_output(embeddings.shape[0])
    resources("TRANSFORM START")
    transform_all(embeddings, reducer, output, start_row)
    resources("END")

    del output, reducer, embeddings
    gc.collect()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
