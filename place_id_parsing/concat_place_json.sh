
: > places.json
: > places_w_error.json

for city in `echo "amsterdam portland Greater-London"`
do
  echo $city
  for f in `ls "/mnt/common-hdd/raw-sources/twitter-data/raw-data/"$city"/place_ids/"`
  do
      if bash utils/place_json_filter.sh "/mnt/common-hdd/raw-sources/twitter-data/raw-data/"$city"/place_ids/"$f | jq -c . > /dev/null; then
      bash utils/place_json_filter.sh "/mnt/common-hdd/raw-sources/twitter-data/raw-data/"$city"/place_ids/"$f | jq -c . >> places.json
      else
      echo bash utils/place_json_filter.sh "/mnt/common-hdd/raw-sources/twitter-data/raw-data/"$city"/place_ids/"$f >> places_w_error.json
      fi
  done
done
