#!/bin/bash
cd /home/sandorjuhasz-ab/eu_twitter_engineering/code/02_place_id_parsing
jupyter nbconvert --to notebook --execute --inplace convert_places.ipynb --ExecutePreprocessor.timeout=7200
