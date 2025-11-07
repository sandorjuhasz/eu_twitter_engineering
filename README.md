# Data Engineering Process for Twitter-Based Social Networks of European Cities

> **Status:** `work-in-progress`

This repository documents the data engineering workflow for constructing Twitter-based social networks of **European cities**.  
Data collection focused on **Amsterdam**, **London**, and **Portland (US)** as a benchmark case.

---

### Repository Structure
```
├── code/
│   ├── 01_user_selection_for_followers/     # Initial user selection for data collection
│   │   └── users_to_query.ipynb             # Selection process notebook
│   │
│   ├── 02_place_id_parsing/                 # Place data processing scripts
│   │   ├── concat_place_json.sh             # JSON concatenation script
│   │   ├── convert_places.ipynb             # Place conversion and cleaning
│   │   └── utils/                           # Related utility scripts
│   │
│   ├── 03_tweet_parsing/                    # Tweet data processing
│   │
│   └── 10_sql_db/                           # Database setup and management
│       └── create_db.sql                    # SQL schema and initialization
```