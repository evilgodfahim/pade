# mk_download.sh
#!/usr/bin/env bash
# Downloads API responses, HTML and referenced JS/CSS into mk/YYYYMMDD/ using BD time.
set -euo pipefail
EDITION_ID="${1:-1}"
# default edition date uses Bangladesh time
EDITION_DATE="${2:-$(TZ='Asia/Dhaka' date +'%d/%m/%Y')}"
BASE="https://epaper.prothomalo.com"
OUTDIR="mk/$(TZ='Asia/Dhaka' date +'%Y%m%d')"
mkdir -p "$OUTDIR"

curl -s -L "${BASE}/Home/GetAllpages?editionid=${EDITION_ID}&editiondate=${EDITION_DATE}" -o "${OUTDIR}/GetAllpages.json" || true

jq -r '.[].PageId' "${OUTDIR}/GetAllpages.json" 2>/dev/null | while read -r pid; do
  curl -s -L "${BASE}/Home/getStoriesOnPage?pageid=${pid}" -o "${OUTDIR}/getStoriesOnPage_${pid}.json" || true
done

curl -s -L "${BASE}/" -o "${OUTDIR}/home.html" || true
curl -s -L "${BASE}/Home/MIndex?eid=${EDITION_ID}&edate=${EDITION_DATE}" -o "${OUTDIR}/MIndex.html" || true

grep -oP '(src|href)=\"\K[^\"]+' "${OUTDIR}/home.html" | egrep -i '\.js$|\.css$' | sort -u | while read -r url; do
  if [[ "$url" =~ ^/ ]]; then
    full="${BASE}${url}"
  elif [[ "$url" =~ ^https?:// ]]; then
    full="$url"
  else
    full="${BASE}/${url}"
  fi
  fname=$(echo "$full" | sed 's|[:/?=&]|_|g')
  curl -s -L "$full" -o "${OUTDIR}/${fname}" || true
done

echo "${OUTDIR}"
