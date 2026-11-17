#!/usr/bin/env bash
# Is <domain> actually bound to Cloud Run yet?
#
#   ./scripts/check_domains.sh                       # uses .env WEB_DOMAIN / INDEX_DOMAIN
#   ./scripts/check_domains.sh lirify.joscart.win
#
# Per host it reports: the DNS answer (via DNS-over-HTTPS, so no `dig` needed),
# whether the record is still behind Cloudflare's proxy, the TLS certificate
# issuer (must be Google's for a Cloud Run managed certificate) and the HTTP
# status. Read-only.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

hosts=("$@")
if [ ${#hosts[@]} -eq 0 ]; then
  hosts=("${WEB_DOMAIN:-lirify.joscart.win}" "${INDEX_DOMAIN:-index.joscart.win}")
fi

doh() {
  # $1 host, $2 type -> prints the answers, one per line
  curl -s -m 10 "https://cloudflare-dns.com/dns-query?name=$1&type=$2" \
    -H 'accept: application/dns-json' 2>/dev/null \
    | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for answer in d.get('Answer', []):
    print(answer.get('data', ''))
"
}

printf '%-28s %-46s %-11s %s\n' HOST "DNS" CERT HTTP
fail=0
for host in "${hosts[@]}"; do
  cname=$(doh "$host" CNAME | head -1)
  addrs=$(doh "$host" A | tr '\n' ' ')
  dns="${cname:-$addrs}"
  [ -z "$dns" ] && dns="(no record)"

  issuer=""
  if command -v openssl >/dev/null 2>&1; then
    issuer=$(echo | timeout 15 openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null \
      | openssl x509 -noout -issuer 2>/dev/null | sed 's/^issuer=//')
  fi
  case "$issuer" in
    *Google*Trust*) tls="google" ;;
    *Cloudflare*|*WE1*|*E1*|*"Google Trust Services LLC"*) tls="cloudflare" ;;
    "") tls="-" ;;
    *) tls="other" ;;
  esac

  code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -L "https://$host/" 2>/dev/null || true)
  [ -z "$code" ] && code="000"
  [ "$code" != "200" ] && fail=1

  printf '%-28s %-46s %-11s %s\n' "$host" "$dns" "$tls" "$code"

  case "$cname" in
    ghs.googlehosted.com.*) : ;;
    "") echo "    -> no CNAME yet: add the record from the deploy job summary" ;;
    *) echo "    -> CNAME does not point at ghs.googlehosted.com" ;;
  esac
  if [ "$tls" = "cloudflare" ] || [[ "$addrs" == *104.21.* || "$addrs" == *172.67.* ]]; then
    echo "    -> resolved to Cloudflare's proxy: set the record to DNS only (grey cloud),"
    echo "       otherwise Google cannot issue the managed certificate"
  fi
done

exit "$fail"
