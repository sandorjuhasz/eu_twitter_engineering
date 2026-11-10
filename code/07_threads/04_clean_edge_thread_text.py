"""Clean London edge-thread text and count whitespace-separated tokens.

Adds edge_thread_cleaned and n_cleaned_words to the existing PostgreSQL
edge corpus without modifying edge_thread_text. On subsequent runs,
existing cleaned text is preserved and only missing values are filled in,
allowing the script to resume after interruption.
"""

import html
import json
import re
import time
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# Settings
CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"
TABLE = "interaction_edge_thread_corpus_london"
BATCH_SIZE = 10_000

# Regexes
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]+")
HASHTAG_RE = re.compile(r"#([^\s#]+)")
MALFORMED_ENTITY_RE = re.compile(r"&(amp|gt|lt|quot|apos);+", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def clean_text(value):
    if value is None:
        return None
    
    # Repair malformed HTML entities and decode HTML characters.
    value = MALFORMED_ENTITY_RE.sub(lambda m: f"&{m.group(1)};", value)
    value = html.unescape(value)
    # Replace URLs and user mentions with standardized placeholders.
    value = URL_RE.sub("URL", value)
    value = MENTION_RE.sub("@USER", value)
    # Remove hashtag symbols while keeping the hashtag text.
    value = HASHTAG_RE.sub(r"\1", value)
    # Normalize whitespace and remove leading/trailing spaces.
    return WHITESPACE_RE.sub(" ", value).strip()


def write_batch(engine, query, batch):
    with engine.begin() as connection:
        connection.execute(query, batch)


def main():
    # Load PostgreSQL credentials and establish the database connection.
    with open(CONNECTION_PATH, encoding="utf-8") as file:
        cfg = json.load(file)

    engine = create_engine(
        URL.create(
            "postgresql+psycopg2",
            username=cfg["user"], password=cfg["password"],
            host=cfg["host"], port=cfg["port"], database=cfg["database"],
        ),
        pool_pre_ping=True,
    )

    try:
        # Add output columns if missing, without modifying existing data.
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS edge_thread_cleaned TEXT"))
            connection.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS n_cleaned_words BIGINT"))

        # Process only rows with original text and missing cleaned text or word counts.
        pending = "edge_thread_text IS NOT NULL AND (edge_thread_cleaned IS NULL OR n_cleaned_words IS NULL)"
        with engine.connect() as connection:
            total = connection.execute(text(f"SELECT COUNT(*) FROM {TABLE} WHERE {pending}")).scalar_one()
        log(f"Rows to process: {total:,}")

        if total == 0:
            log("Nothing to update.")
            return

        # Read pending rows and update cleaned text and word counts using edge identifiers.
        select_sql = text(f"""
            SELECT city, user_id1, user_id2, edge_thread_text, edge_thread_cleaned
            FROM {TABLE}
            WHERE {pending}
        """)
        update_sql = text(f"""
            UPDATE {TABLE}
            SET edge_thread_cleaned = :edge_thread_cleaned,
                n_cleaned_words = :n_cleaned_words
            WHERE city = :city AND user_id1 = :user_id1 AND user_id2 = :user_id2
        """)

        started = time.time()
        processed = 0
        batch = []
        log("Cleaning edge-thread text")

        # Stream rows to avoid loading the entire corpus into memory.
        with engine.connect().execution_options(stream_results=True) as read_connection:
            for row in read_connection.execute(select_sql).mappings():

                # Preserve existing cleaned text; otherwise clean the original text.
                cleaned = row["edge_thread_cleaned"]
                if cleaned is None:
                    cleaned = clean_text(row["edge_thread_text"])

                # Count whitespace-separated tokens and prepare the database update.
                batch.append({
                    "city": row["city"],
                    "user_id1": row["user_id1"],
                    "user_id2": row["user_id2"],
                    "edge_thread_cleaned": cleaned,
                    "n_cleaned_words": len(cleaned.split()) if cleaned else 0,
                })

                # Write completed batches and report processing speed and remaining time.
                if len(batch) >= BATCH_SIZE:
                    write_batch(engine, update_sql, batch)
                    processed += len(batch)
                    batch.clear()
                    elapsed = time.time() - started
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (total - processed) / rate / 60 if rate > 0 else 0
                    log(f"{processed:,}/{total:,} ({processed / total:.1%}) | {rate:,.0f} rows/s | ETA {eta:.1f} min")

        # Write any remaining rows after the final full batch.
        if batch:
            write_batch(engine, update_sql, batch)
            processed += len(batch)

        # Check output coverage, missing values, and empty cleaned texts.
        with engine.connect() as connection:
            stats = connection.execute(text(f"""
                SELECT COUNT(*) AS n_rows,
                       COUNT(edge_thread_text) AS n_original_text,
                       COUNT(edge_thread_cleaned) AS n_cleaned_text,
                       COUNT(n_cleaned_words) AS n_cleaned_word_counts,
                       COUNT(*) FILTER (WHERE edge_thread_text IS NOT NULL AND edge_thread_cleaned IS NULL) AS n_missing_cleaned,
                       COUNT(*) FILTER (WHERE edge_thread_cleaned IS NOT NULL AND n_cleaned_words IS NULL) AS n_missing_word_count,
                       COUNT(*) FILTER (WHERE edge_thread_cleaned IS NOT NULL AND n_cleaned_words = 0) AS n_zero_word_count
                FROM {TABLE}
            """)).mappings().one()

        log("Output checks")
        for name, value in stats.items():
            log(f"{name}: {value:,}")

        # Refresh PostgreSQL statistics after updating the corpus.
        with engine.begin() as connection:
            connection.execute(text(f"ANALYZE {TABLE}"))

        log(f"Finished: {processed:,} rows in {(time.time() - started) / 60:.2f} minutes")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
