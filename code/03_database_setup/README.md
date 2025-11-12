# Database Setup

This folder contains scripts for setting up the PostgreSQL database and loading Twitter data into various tables using PySpark for data processing.

## Overview

The database setup process consists of multiple steps that create and populate tables for tweets, users, places, and interaction networks. Each script uses PySpark to process raw Twitter data from `/mnt/common-hdd/raw-sources/twitter-data/data` and `psycopg2` to create and manage PostgreSQL tables.

## Running all

If you are sure about the prerequisites and the content of the scripts, run all the database setup scripts in order, execute the following commands from the `03_database_setup` directory:

```bash
python 00_database.py
python 01_tweet_table.py
python 02_follower_table.py
python 03_interaction_networks.py
python 04_place_table.py
```

## Prerequisites

- **Python packages:**
  - `pyspark` (with sufficient driver memory configured, and ODBC jar for PostgreSQL downloaded and placed in the appropriate Spark jars directory)
  - `psycopg2`
  - `ujson`
  
- **PostgreSQL database** with connection configured in `connection.json`

- **Connection Configuration:** Copy `connection_sample.json` to `connection.json` and fill in your database credentials:
  ```json
  {
      "database": "your_database_name",
      "user": "your_username", 
      "host": "localhost",
      "password": "your_password",
      "port": 5432
  }
  ```

## Execution Order

Run the scripts in numerical order:

### 0. Create Database
```bash
python 00_database.py
```
Creates the PostgreSQL database specified in `connection.json`. Only needed if the database doesn't already exist.

### 1. Tweet Table
```bash
python 01_tweet_table.py
```
Creates and populates the `tweet` table with:
- `city` - City identifier (VARCHAR)
- `tweet_id` - Unique tweet ID (BIGINT)
- `user_id` - Author's user ID (BIGINT)
- `created_at` - Tweet timestamp (TIMESTAMP)
- `place_id` - Associated place ID (VARCHAR)
- `lat`, `lon` - Geographic coordinates (FLOAT)
- `conversation_id` - Thread/conversation ID (BIGINT)
- `text` - Tweet text content (TEXT)

### 2. Follower Network Table
```bash
python 02_follower_table.py
```
Creates and populates the `follower_network` table with:
- `user_id1_source` - Follower user ID (BIGINT)
- `user_id2_target` - Following user ID (BIGINT)

This table represents the directed follower graph where user1 follows user2.

### 3. Interaction Networks
```bash
python 03_interaction_networks.py
```
Creates and populates two interaction network tables:

**mention_network:**
- `city` - City identifier (VARCHAR)
- `tweet_id` - Tweet ID containing mention (BIGINT)
- `created_at` - Mention timestamp (TIMESTAMP)
- `user_id1_source` - Author who mentioned (BIGINT)
- `user_id2_interaction` - Mentioned user (BIGINT)

Note that in the same tweet, a user may mention multiple users, resulting in multiple rows for that tweet in this table.

**reply_network:**
- `city` - City identifier (VARCHAR)
- `tweet_id` - Reply tweet ID (BIGINT)
- `conversation_id` - Original thread ID (BIGINT)
- `created_at` - Reply timestamp (TIMESTAMP)
- `user_id1_source` - Author who replied (BIGINT)
- `user_id2_interaction` - User being replied to (BIGINT)

Here, `conversation_id` links all replies and replies to replies to the original tweet in the thread.

### 4. Place Table
```bash
python 04_place_table.py
```
Creates and populates the `place` table with geographic metadata:
- `place_id` - Twitter place identifier (VARCHAR)
- `place_name` - Short place name (VARCHAR)
- `full_name` - Full place name (VARCHAR)
- `country_code` - ISO 2-char country code (VARCHAR)
- `place_type` - Type of place (VARCHAR)
- `lon_min`, `lon_max`, `lat_min`, `lat_max` - Bounding box coordinates (FLOAT)
- `centroid_lon`, `centroid_lat` - Center coordinates (FLOAT)
- `err` - Coordinate error/uncertainty, equals to half of the diameter of the bounding box (FLOAT)

## Additional Files

- **`connection_sample.json`** - Template for database connection configuration
- **`connection.json`** - (gitignored) Actual database credentials not added to the repository

## Notes

- Each script **drops existing tables** before recreating them, so be careful with existing data
- Scripts use PySpark for processing large datasets efficiently
- All scripts expect to be run from the `03_database_setup` directory
- Memory configuration for Spark driver is set to 50g in most scripts - adjust based on your system
- The shebang (`#!/mnt/common-hdd/bokanyie/anaconda3/bin/python`) may need to be updated for your environment

## Database Schema

The complete database schema includes:
- **tweet** - Core tweet data with location and text
- **follower_network** - User following relationships
- **mention_network** - @mention interactions
- **reply_network** - Reply interactions
- **place** - Geographic place metadata

These tables enable analysis of both the follower network structure and temporal interaction patterns across different cities.
