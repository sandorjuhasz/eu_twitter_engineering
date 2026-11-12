
#!/usr/bin/env python3
"""Generate restartable full-corpus SentenceTransformer embeddings in deterministic SQL order."""

import gc, json, shutil, time
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sentence_transformers import SentenceTransformer
from pipeline_config import *

COUNT_PATH = SHARED_DIR / "n_documents.txt"
EMBEDDINGS_PATH = SHARED_DIR / "embeddings_384d.npy"
PROGRESS_PATH = SHARED_DIR / "embedding_progress.json"
METADATA_PATH = SHARED_DIR / "embedding_metadata.json"


def engine_from_config():
    with open(CONNECTION_PATH, encoding="utf-8") as f:
        c = json.load(f)
    return create_engine(
        URL.create(
            "postgresql+psycopg2",
            username=c["user"],
            password=c["password"],
            host=c["host"],
            port=c["port"],
            database=c["database"]
        ),
        pool_pre_ping=True
    )


def count_documents(engine):
    if COUNT_PATH.exists():
        return int(COUNT_PATH.read_text().strip())

    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""SELECT COUNT(*)
                    FROM {SOURCE_TABLE}
                    WHERE {TEXT_COLUMN} IS NOT NULL
                      AND n_cleaned_words >= %s""",
                (MIN_CLEANED_WORDS,)
            )
            n = int(cur.fetchone()[0])
        finally:
            cur.close()
    finally:
        conn.close()

    COUNT_PATH.write_text(str(n))
    return n


def main():
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    engine = engine_from_config()
    n = count_documents(engine)

    if EMBEDDINGS_PATH.exists() and not PROGRESS_PATH.exists():
        a = np.load(EMBEDDINGS_PATH, mmap_mode="r")
        if a.shape == (n, EMBEDDING_DIM):
            print("Embeddings already complete.")
            engine.dispose()
            return
        raise RuntimeError(f"Unexpected embedding shape: {a.shape}")

    model = SentenceTransformer(MODEL_NAME)
    model.max_seq_length = MAX_SEQ_LENGTH

    if EMBEDDINGS_PATH.exists():
        out = np.lib.format.open_memmap(
            EMBEDDINGS_PATH, mode="r+"
        )
    else:
        out = np.lib.format.open_memmap(
            EMBEDDINGS_PATH,
            mode="w+",
            dtype=np.float32,
            shape=(n, EMBEDDING_DIM)
        )

    start = (
        int(json.loads(PROGRESS_PATH.read_text())["completed_rows"])
        if PROGRESS_PATH.exists()
        else 0
    )

    conn = engine.raw_connection()
    cur = conn.cursor(name="embedding_stream")
    cur.itersize = DB_FETCH_SIZE

    cur.execute(
        f"""SELECT {TEXT_COLUMN}
            FROM {SOURCE_TABLE}
            WHERE {TEXT_COLUMN} IS NOT NULL
              AND n_cleaned_words >= %s
            ORDER BY {', '.join(ORDER_COLS)}
            OFFSET %s""",
        (MIN_CLEANED_WORDS, start)
    )

    row = start
    last_flush = row
    t0 = time.time()

    try:
        while True:
            records = cur.fetchmany(DB_FETCH_SIZE)
            if not records:
                break

            texts = [r[0] for r in records]

            emb = model.encode(
                texts,
                batch_size=EMBED_BATCH_SIZE,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=False
            ).astype(np.float32, copy=False)

            end = row + len(texts)
            out[row:end] = emb
            row = end

            if row - last_flush >= EMBED_FLUSH_EVERY or row == n:
                out.flush()
                PROGRESS_PATH.write_text(
                    json.dumps(
                        {
                            "completed_rows": row,
                            "n_documents": n
                        },
                        indent=2
                    )
                )

                rate = (row - start) / max(time.time() - t0, 1e-9)
                eta = (n - row) / rate / 3600 if rate else float("nan")

                print(
                    f"{row:,}/{n:,} ({row/n:.2%}); "
                    f"{rate:.1f} docs/s; ETA={eta:.1f} h",
                    flush=True
                )

                last_flush = row

    finally:
        cur.close()
        conn.close()
        engine.dispose()

    if row != n:
        raise RuntimeError(f"Row mismatch: {row:,} vs {n:,}")

    out.flush()
    PROGRESS_PATH.unlink(missing_ok=True)

    METADATA_PATH.write_text(
        json.dumps(
            {
                "n_documents": n,
                "source_table": SOURCE_TABLE,
                "text_column": TEXT_COLUMN,
                "filter": f"n_cleaned_words >= {MIN_CLEANED_WORDS}",
                "order": list(ORDER_COLS),
                "embedding_model": MODEL_NAME,
                "max_seq_length": MAX_SEQ_LENGTH,
                "embedding_dim": EMBEDDING_DIM
            },
            indent=2
        )
    )

    del out, model
    gc.collect()
    print("DONE")


if __name__ == "__main__":
    main()
