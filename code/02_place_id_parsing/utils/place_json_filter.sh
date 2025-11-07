cat $1 | \
    sed -E "s/(\"[^\"]*?)'([^\"]*?\")/\1\\\'\2/g" |\
    sed -E -e 's/Place\(|BoundingBox\(/{/g' |\
    sed -e 's/)/}/g' |\
    sed -E -e 's/([{ ])([^={},]+?)=/\1"\2":/g' |\
    sed 's/</"/g' |\
    sed 's/>/"/g' |\
    sed -E "s/([^\\])'/\1\"/g" |\
    sed "s/None/ null/g" |\
    sed -E "s/\\\'/\'/g"
# | jq -c .


