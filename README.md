# Data Engineering Process for Twitter-Based Social Networks of European Cities

> **Status:** `work-in-progress`

This repository documents the data engineering workflow for constructing Twitter-based social networks of **European cities**.  
Data collection focused on **Amsterdam**, **London**, and **Portland (US)** as a benchmark case.

---

### Repository Structure
```
├── code/
│   ├── 00_response_processing/              # Field definitions and CSV schema of the collected data
│   │
│   ├── 01_user_selection_for_followers/     # Initial user selection for data collection
│   │   └── users_to_query.ipynb             # Selection process notebook
│   │
│   ├── 02_place_id_parsing/                 # Place data processing scripts
│   │   ├── concat_place_json.sh             # JSON concatenation script
│   │   ├── convert_places.ipynb / .py       # Place conversion and cleaning
│   │   └── utils/                           # Place JSON filtering utility
│   │
│   ├── 03_database_setup/                   # Database setup and table creation
│   │   ├── README.md                        # Detailed setup documentation
│   │   ├── 00_database.py                   # Database initialization
│   │   ├── 01_tweet_table.py                # Tweet table creation and loading
│   │   ├── 02_follower_table.py             # Follower network table
│   │   ├── 03_interaction_networks.py       # Mention and reply network tables
│   │   ├── 04_place_table.py                # Place/location table
│   │   ├── 05_text_extras.py                # Text-related extras
│   │   ├── 06_user_table.py                 # User table
│   │   └── connection_sample.json           # Database connection template (copy to connection.json)
│   │
│   ├── 05_home_processing/                  # Home location detection
│   │   ├── home_pipeline/                   # Current SQL pipeline on schema `revised` (twitter_cities_v2)
│   │   │   ├── DECISIONS.md                 # Rules, parameters and check results (read first)
│   │   │   ├── sql/                         # 00 checks, 01 input, 02 cell counts, 03 homes,
│   │   │   │                                #   05 diagnostics, 06 final table `revised.home_final`
│   │   │   └── home_overview.ipynb          # Numbers, maps and rule illustrations of the homes
│   │   └── zita_notebooks/                  # Earlier notebook-based home detection (legacy, `_zi` tables)
│   │
│   ├── 06_networks/                         # Interaction network construction and descriptives
│   ├── 07_threads/                          # Conversation / thread tables and edge-level corpus
│   └── 08_topic_models/                     # Edge-level topic modelling pipeline
│
├── external_data/                           # Third-party data used in the analysis
│   └── population/                          # GHS-POP 2015 population per H3 cell (res 8/9/10),
│                                            #   build script and README (source, licence, caveats)
│
├── config/                                  # Path configuration (config_paths.yaml)
├── notes/                                   # Plans and documentation notes
│
├── data/                                    # Symbolic link to data directory (server only)
└── raw-data/                                # Symbolic link to raw data directory (server only)
```

### Home locations

Home detection runs as set-based SQL on the server (`code/05_home_processing/home_pipeline/sql/`, run in order;
each script has session settings S1, build steps S2 and verification queries V*). The final table
`revised.home_final` holds one home per (city, user, H3 res 10 / 9): the cell with the most distinct nights
(20:00-08:00 local time), for users with >= 10 tweets, >= 3 nights in the home cell and a strict lead over the
second cell. All choices and check results are logged in `DECISIONS.md`.

Do not put data files under `code/`: external data go to `external_data/`. The root `data/` is reserved for the
server's raw-data symlink.

### SQL Team

**Shared PostgreSQL Role:** `twitter_project`

All database objects (tables, views, etc.) should be owned by the shared role  
so every team member can manage them (ALTER, DROP, GRANT, etc.).

**Base SQL template for creating new tables:**

```sql
SET ROLE twitter_project;

CREATE TABLE public.team_test (...);

RESET ROLE;
```