# Data Engineering Process for Twitter-Based Social Networks of European Cities

> **Status:** `work-in-progress`

This repository documents the data engineering workflow for constructing Twitter-based social networks of **European cities**.  
Data collection focused on **Amsterdam**, **London**, and **Portland (US)** as a benchmark case.

---

### Repository Structure
```
├── code/
│   ├── 01_user_selection_for_followers/     # Initial user selection for data collection
│   │   ├── users_to_query.ipynb             # Selection process notebook
│   │   ├── selected_users_amsterdam.csv     # Selected users for Amsterdam
│   │   └── selected_users_portland.csv      # Selected users for Portland
│   │
│   ├── 02_place_id_parsing/                 # Place data processing scripts
│   │   ├── concat_place_json.sh             # JSON concatenation script
│   │   ├── convert_places.ipynb             # Place conversion and cleaning
│   │   ├── places_all.json                  # Consolidated place data
│   │   └── utils/
│   │       └── place_json_filter.sh         # Place JSON filtering utility
│   │
│   └── 03_database_setup/                   # Database setup and table creation
│       ├── README.md                        # Detailed setup documentation
│       ├── 00_database.py                   # Database initialization
│       ├── 01_tweet_table.py                # Tweet table creation and loading
│       ├── 02_follower_table.py             # Follower network table
│       ├── 03_interaction_networks.py       # Mention and reply network tables
│       ├── 04_place_table.py                # Place/location table
│       └── connection_sample.json           # Database connection template
│
├── tables/                                  # Output tables
│   ├── place.csv                            # Place reference data
│   └── test_tweet_table.csv                 # Sample tweet data
│
├── data/                                    # Symbolic link to data directory
└── raw-data/                                # Symbolic link to raw data directory
```

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