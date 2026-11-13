#!/usr/bin/env python3
"""
09_attach_edge_topics.py

Attach final K=175 topic assignments and the human-coded taxonomy DIRECTLY to
interaction_edge_thread_corpus_london.

No permanent auxiliary topic table is created.

Only eligible edges receive topic information:
    edge_thread_cleaned IS NOT NULL
    AND n_cleaned_words >= 10

All other rows remain NULL in the new topic/taxonomy columns.

Alignment invariant:
    eligible DB row i in ORDER BY city,user_id1,user_id2
    == topics_k175.npy[i]

Implementation:
- ALTER the existing corpus table to add output columns if missing.
- Stream eligible edges in the exact embedding order.
- Write each chunk to a TEMP table.
- UPDATE the original corpus table from that TEMP table.
- Commit after every chunk, so the script is restart-safe.
- On restart, already populated edges are skipped for writing, but ALL eligible
  rows are still streamed so NumPy row alignment remains unchanged.

The script NEVER recomputes topics.
"""

import csv
import io
import json
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2 import sql

from pipeline_config import (
    CONNECTION_PATH,
    SOURCE_TABLE,
    TEXT_COLUMN,
    MIN_CLEANED_WORDS,
    ORDER_COLS,
    KMEANS_DIR,
    TAXONOMY_DIR,
    FINAL_K,
    DB_FETCH_SIZE,
)

if FINAL_K != 175:
    raise ValueError(f"This taxonomy export expects FINAL_K=175, got {FINAL_K}")

FINAL_DIR = KMEANS_DIR / "final_model"
WRITE_CHUNK = 100_000

TOPIC_CANDIDATES = [
    FINAL_DIR / f"topics_k{FINAL_K}.npy",
    FINAL_DIR / "topics.npy",
]
DISTANCE_CANDIDATES = [
    FINAL_DIR / f"assigned_centroid_distance_k{FINAL_K}.npy",
    FINAL_DIR / "assigned_centroid_distance.npy",
]
LOW_CONF_CANDIDATES = [
    FINAL_DIR / f"low_confidence_k{FINAL_K}.npy",
    FINAL_DIR / "low_confidence.npy",
]

TAXONOMY_PATH = TAXONOMY_DIR / "k175_final_taxonomy_mapping.csv"

def first_existing(candidates, required=False, label="file"):
    for p in candidates:
        if p.exists():
            return p
    if required:
        raise FileNotFoundError(
            f"Could not find required {label}. Checked:\n  "
            + "\n  ".join(str(p) for p in candidates)
        )
    return None


def load_connection_kwargs(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    for key in ("postgres", "postgresql", "database", "db"):
        if key in cfg and isinstance(cfg[key], dict):
            cfg = cfg[key]
            break

    aliases = {
        "database": "dbname",
        "name": "dbname",
        "username": "user",
    }
    out = {}
    for k, v in cfg.items():
        kk = aliases.get(k, k)
        if kk in {"dbname", "user", "password", "host", "port", "sslmode"}:
            out[kk] = v
    return out


def load_taxonomy(path):
    required = [
        "topic",
        "fine_label",
        "dense_category_v3",
        "broad_category_v3",
        "super_domain",
        "topic_type",
        "analytical_class",
        "semantic_coherence",
        "coding_confidence",
        "main_substantive_sample",
        "descriptive_sample",
        "analysis_recommendation",
    ]

    if not path.exists():
        raise FileNotFoundError(f"Taxonomy mapping not found: {path}")

    mapping = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Taxonomy CSV missing columns: {missing}")
        for row in reader:
            mapping[int(row["topic"])] = row

    expected = set(range(FINAL_K))
    observed = set(mapping)
    if observed != expected:
        raise ValueError(
            f"Taxonomy must contain exactly topics 0..{FINAL_K-1}. "
            f"Missing={sorted(expected-observed)}, extra={sorted(observed-expected)}"
        )
    return mapping


def clean_copy_value(x):
    if x is None or x == "":
        return r"\N"
    return (
        str(x)
        .replace("\\", "\\\\")
        .replace("\t", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def float_value(arr, i):
    if arr is None:
        return r"\N"
    x = float(arr[i])
    return repr(x) if np.isfinite(x) else r"\N"


def bool_value(arr, i):
    if arr is None:
        return r"\N"
    return "t" if bool(arr[i]) else "f"


def main():
    if list(ORDER_COLS) != ["city", "user_id1", "user_id2"]:
        raise ValueError(
            "Safety stop: ORDER_COLS is not exactly "
            "['city', 'user_id1', 'user_id2']. "
            f"Current value: {ORDER_COLS}"
        )

    topic_path = first_existing(TOPIC_CANDIDATES, True, "topic array")
    distance_path = first_existing(DISTANCE_CANDIDATES)
    low_conf_path = first_existing(LOW_CONF_CANDIDATES)

    topics = np.load(topic_path, mmap_mode="r")
    distances = np.load(distance_path, mmap_mode="r") if distance_path else None
    low_conf = np.load(low_conf_path, mmap_mode="r") if low_conf_path else None
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    n = len(topics)

    if distances is not None and len(distances) != n:
        raise ValueError("Distance array length does not match topic array.")
    if low_conf is not None and len(low_conf) != n:
        raise ValueError("Low-confidence array length does not match topic array.")
    if int(topics.min()) < 0 or int(topics.max()) >= FINAL_K:
        raise ValueError("Topic array contains labels outside 0..174.")

    print("[1/6] Loading inputs", flush=True)
    print(f"Source table:  {SOURCE_TABLE}")
    print(f"Topics:        {topic_path}")
    print(f"Rows:          {n:,}")
    print(f"Taxonomy:      {TAXONOMY_PATH}")
    print(f"Distance:      {distance_path or 'not found -> NULL'}")
    print(f"Low conf.:     {low_conf_path or 'not found -> NULL'}")
    print()
    print("Mode: UPDATE EXISTING USER-USER CORPUS TABLE")
    print("No permanent auxiliary topic table will be created.")

    conn = psycopg2.connect(**load_connection_kwargs(CONNECTION_PATH))
    conn.autocommit = False

    # 1. Exact eligibility-count safety check BEFORE altering the source table.
    count_q = sql.SQL("""
        SELECT COUNT(*)
        FROM {source}
        WHERE {textcol} IS NOT NULL
          AND n_cleaned_words >= %s
    """).format(
        source=sql.Identifier(SOURCE_TABLE),
        textcol=sql.Identifier(TEXT_COLUMN),
    )

    with conn.cursor() as cur:
        cur.execute(count_q, (MIN_CLEANED_WORDS,))
        db_n = cur.fetchone()[0]

    if db_n != n:
        conn.close()
        raise RuntimeError(
            "ROW ALIGNMENT SAFETY CHECK FAILED.\n"
            f"Eligible DB rows: {db_n:,}\n"
            f"Topic labels:     {n:,}\n"
            "No source-table changes were made."
        )

    print(f"Eligibility check OK: {db_n:,} DB rows = {n:,} topic labels")

    print(f"      OK: {db_n:,} DB rows = {n:,} topic labels", flush=True)

    # 3. Add final columns to the EXISTING corpus table.
    column_defs = [
        ("topic_k175", "SMALLINT"),
        ("topic_fine_label", "TEXT"),
        ("topic_dense_category", "TEXT"),
        ("topic_broad_category", "TEXT"),
        ("topic_super_domain", "TEXT"),
        ("topic_type", "TEXT"),
        ("topic_analytical_class", "TEXT"),
        ("topic_semantic_coherence", "TEXT"),
        ("topic_coding_confidence", "TEXT"),
        ("topic_main_substantive_sample", "BOOLEAN"),
        ("topic_descriptive_sample", "BOOLEAN"),
        ("topic_analysis_recommendation", "TEXT"),
        ("topic_assigned_centroid_distance", "DOUBLE PRECISION"),
        ("topic_low_confidence", "BOOLEAN"),
    ]

    with conn.cursor() as cur:
        for col, typ in column_defs:
            cur.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}")
                .format(
                    sql.Identifier(SOURCE_TABLE),
                    sql.Identifier(col),
                    sql.SQL(typ),
                )
            )
    conn.commit()
    print("Topic/taxonomy columns are present.")

    print("[3/6] Checking existing assignments", flush=True)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
                SELECT COUNT(*)
                FROM {source}
                WHERE {textcol} IS NOT NULL
                  AND n_cleaned_words >= %s
                  AND topic_k175 IS NOT NULL
            """).format(
                source=sql.Identifier(SOURCE_TABLE),
                textcol=sql.Identifier(TEXT_COLUMN),
            ),
            (MIN_CLEANED_WORDS,),
        )
        already = cur.fetchone()[0]
    print(f"      already populated: {already:,}", flush=True)
    print(f"      remaining:         {n - already:,}", flush=True)
    if already == 0:
        print("      state: fresh run", flush=True)
    elif already == n:
        print("      state: completed run; verifying existing assignments", flush=True)
    else:
        print("      state: restart/resume", flush=True)

    print("[4/6] Preparing temporary staging table", flush=True)

    # 4. TEMP staging table. It disappears automatically with this DB session.
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE tmp_edge_topics_k175 (
                city TEXT NOT NULL,
                user_id1 BIGINT NOT NULL,
                user_id2 BIGINT NOT NULL,
                topic_k175 SMALLINT NOT NULL,
                topic_fine_label TEXT,
                topic_dense_category TEXT,
                topic_broad_category TEXT,
                topic_super_domain TEXT,
                topic_type TEXT,
                topic_analytical_class TEXT,
                topic_semantic_coherence TEXT,
                topic_coding_confidence TEXT,
                topic_main_substantive_sample BOOLEAN,
                topic_descriptive_sample BOOLEAN,
                topic_analysis_recommendation TEXT,
                topic_assigned_centroid_distance DOUBLE PRECISION,
                topic_low_confidence BOOLEAN
            ) ON COMMIT DELETE ROWS
        """)
    conn.commit()

    # IMPORTANT: scan ALL eligible rows in the exact original order.
    # V2 uses keyset pagination instead of a server-side cursor kept open across
    # commits. This is safer for a long restartable job.
    copy_q = """
        COPY tmp_edge_topics_k175 (
            city, user_id1, user_id2,
            topic_k175,
            topic_fine_label,
            topic_dense_category,
            topic_broad_category,
            topic_super_domain,
            topic_type,
            topic_analytical_class,
            topic_semantic_coherence,
            topic_coding_confidence,
            topic_main_substantive_sample,
            topic_descriptive_sample,
            topic_analysis_recommendation,
            topic_assigned_centroid_distance,
            topic_low_confidence
        )
        FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N')
    """

    update_q = sql.SQL("""
        UPDATE {source} AS s
        SET
            topic_k175 = t.topic_k175,
            topic_fine_label = t.topic_fine_label,
            topic_dense_category = t.topic_dense_category,
            topic_broad_category = t.topic_broad_category,
            topic_super_domain = t.topic_super_domain,
            topic_type = t.topic_type,
            topic_analytical_class = t.topic_analytical_class,
            topic_semantic_coherence = t.topic_semantic_coherence,
            topic_coding_confidence = t.topic_coding_confidence,
            topic_main_substantive_sample = t.topic_main_substantive_sample,
            topic_descriptive_sample = t.topic_descriptive_sample,
            topic_analysis_recommendation = t.topic_analysis_recommendation,
            topic_assigned_centroid_distance = t.topic_assigned_centroid_distance,
            topic_low_confidence = t.topic_low_confidence
        FROM tmp_edge_topics_k175 AS t
        WHERE s.city = t.city
          AND s.user_id1 = t.user_id1
          AND s.user_id2 = t.user_id2
          AND s.topic_k175 IS NULL
    """).format(source=sql.Identifier(SOURCE_TABLE))

    print("[5/6] Attaching topics in deterministic 50k pages", flush=True)

    page_size = 50_000
    last_key = None
    processed = 0
    newly_written = 0
    page = 0

    while True:
        if last_key is None:
            page_q = sql.SQL("""
                SELECT city, user_id1, user_id2, topic_k175
                FROM {source}
                WHERE {textcol} IS NOT NULL
                  AND n_cleaned_words >= %s
                ORDER BY city, user_id1, user_id2
                LIMIT %s
            """).format(
                source=sql.Identifier(SOURCE_TABLE),
                textcol=sql.Identifier(TEXT_COLUMN),
            )
            params = (MIN_CLEANED_WORDS, page_size)
        else:
            page_q = sql.SQL("""
                SELECT city, user_id1, user_id2, topic_k175
                FROM {source}
                WHERE {textcol} IS NOT NULL
                  AND n_cleaned_words >= %s
                  AND (city, user_id1, user_id2) > (%s, %s, %s)
                ORDER BY city, user_id1, user_id2
                LIMIT %s
            """).format(
                source=sql.Identifier(SOURCE_TABLE),
                textcol=sql.Identifier(TEXT_COLUMN),
            )
            params = (
                MIN_CLEANED_WORDS,
                last_key[0], last_key[1], last_key[2],
                page_size,
            )

        with conn.cursor() as cur:
            cur.execute(page_q, params)
            batch = cur.fetchall()

        if not batch:
            break

        page += 1
        buf = io.StringIO()
        staged = 0

        for city, user1, user2, existing_topic in batch:
            if processed >= n:
                raise RuntimeError("DB has more eligible rows than the topic array.")

            i = processed
            expected_topic = int(topics[i])

            # Restart safety: the existing first 100k (or any later completed
            # chunks) must match the original NumPy row exactly.
            if existing_topic is not None:
                if int(existing_topic) != expected_topic:
                    raise RuntimeError(
                        "ALIGNMENT ERROR on already-populated edge:\n"
                        f"row={i:,}, edge=({city},{user1},{user2}), "
                        f"DB topic={existing_topic}, NPY topic={expected_topic}"
                    )
            else:
                tax = taxonomy[expected_topic]
                vals = [
                    clean_copy_value(city),
                    clean_copy_value(user1),
                    clean_copy_value(user2),
                    str(expected_topic),
                    clean_copy_value(tax["fine_label"]),
                    clean_copy_value(tax["dense_category_v3"]),
                    clean_copy_value(tax["broad_category_v3"]),
                    clean_copy_value(tax["super_domain"]),
                    clean_copy_value(tax["topic_type"]),
                    clean_copy_value(tax["analytical_class"]),
                    clean_copy_value(tax["semantic_coherence"]),
                    clean_copy_value(tax["coding_confidence"]),
                    "t" if tax["main_substantive_sample"] == "1" else "f",
                    "t" if tax["descriptive_sample"] == "1" else "f",
                    clean_copy_value(tax["analysis_recommendation"]),
                    float_value(distances, i),
                    bool_value(low_conf, i),
                ]
                buf.write("\t".join(vals) + "\n")
                staged += 1

            processed += 1

        last_key = batch[-1][:3]

        if staged:
            buf.seek(0)
            with conn.cursor() as wcur:
                wcur.copy_expert(copy_q, buf)
                wcur.execute(update_q)
                if wcur.rowcount != staged:
                    raise RuntimeError(
                        f"Chunk mismatch: staged={staged:,}, updated={wcur.rowcount:,}"
                    )
                newly_written += wcur.rowcount

        # Each page is independently durable.
        conn.commit()

        print(
            f"      page {page:>4,} | scanned {processed:>10,}/{n:,} "
            f"| newly written {newly_written:>10,}",
            flush=True,
        )

    if processed != n:
        raise RuntimeError(
            f"Final stream mismatch: processed {processed:,}, expected {n:,}"
        )

    # 5. Final checks.
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
                SELECT
                    COUNT(*) FILTER (
                        WHERE {textcol} IS NOT NULL
                          AND n_cleaned_words >= %s
                    ),
                    COUNT(*) FILTER (
                        WHERE {textcol} IS NOT NULL
                          AND n_cleaned_words >= %s
                          AND topic_k175 IS NOT NULL
                    ),
                    COUNT(*) FILTER (
                        WHERE ({textcol} IS NULL OR n_cleaned_words < %s)
                          AND topic_k175 IS NOT NULL
                    ),
                    COUNT(DISTINCT topic_k175)
                FROM {source}
            """).format(
                source=sql.Identifier(SOURCE_TABLE),
                textcol=sql.Identifier(TEXT_COLUMN),
            ),
            (MIN_CLEANED_WORDS, MIN_CLEANED_WORDS, MIN_CLEANED_WORDS),
        )
        eligible, assigned, ineligible_assigned, distinct_topics = cur.fetchone()

    if eligible != n or assigned != n:
        raise RuntimeError(
            f"Final assignment check failed: eligible={eligible:,}, "
            f"assigned={assigned:,}, expected={n:,}"
        )
    if ineligible_assigned != 0:
        raise RuntimeError(
            f"Safety check failed: {ineligible_assigned:,} ineligible rows "
            "have topic assignments."
        )
    if distinct_topics != FINAL_K:
        raise RuntimeError(
            f"Expected {FINAL_K} distinct topics, found {distinct_topics}."
        )

    # Indexes are optional but useful for downstream analysis.
    # CREATE INDEX IF NOT EXISTS is restart-safe.
    print("Creating/checking topic indexes...")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (topic_k175)")
            .format(
                sql.Identifier(f"{SOURCE_TABLE}_topic_k175_idx"),
                sql.Identifier(SOURCE_TABLE),
            )
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {} "
                "(topic_dense_category)"
            ).format(
                sql.Identifier(f"{SOURCE_TABLE}_topic_dense_idx"),
                sql.Identifier(SOURCE_TABLE),
            )
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {} "
                "(topic_broad_category)"
            ).format(
                sql.Identifier(f"{SOURCE_TABLE}_topic_broad_idx"),
                sql.Identifier(SOURCE_TABLE),
            )
        )
    conn.commit()

    print("\nDONE")
    print(f"Updated table:        {SOURCE_TABLE}")
    print(f"Eligible edges:       {eligible:,}")
    print(f"Topic-assigned edges: {assigned:,}")
    print(f"Ineligible assigned:  {ineligible_assigned:,}")
    print(f"Distinct K175 topics: {distinct_topics}")
    print(f"Newly written now:    {newly_written:,}")

    conn.close()


if __name__ == "__main__":
    main()
