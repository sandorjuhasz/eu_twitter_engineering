#!/mnt/common-hdd/bokanyie/anaconda3/bin/python

import psycopg2 as psql 
import ujson as json

# opening connection, storing parameters and database name separately
connection_dict = json.load(open("connection.json"))
database = connection_dict["database"]
del connection_dict["database"]


# create connection to default database to create new database
conn = psql.connect(**connection_dict, database = "postgres")
conn.set_isolation_level(psql.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()

# create database
query = f"""
SET ROLE twitter_project;

CREATE DATABASE {database}
    WITH 
    OWNER = {connection_dict["user"]}
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    CONNECTION LIMIT = -1;

RESET ROLE;
"""

cur.execute(query)
conn.commit()

# closing connection
cur.close()
conn.close()

print(f"Database {database} created.")