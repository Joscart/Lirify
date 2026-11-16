#!/usr/bin/env bash
# Is <domain> actually bound to Cloud Run yet?
#
#   ./scripts/check_domains.sh                       # uses .env WEB_DOMAIN / INDEX_DOMAIN
#   ./scripts/check_domains.sh lirify.joscart.win
#
# Checks, per host: DNS answer, whether it is still behind Cloudflare's proxy,
# the TLS certificate issuer, and the HTTP status. Read-only.
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
  hosts=("${WEB_DOMAIN:-lirify.joscart.win}" "${INDEX_DOMAIN:-index.lirify.joscart.win}")
fi

printf '%-30s %-46s %-10s %s\n' HOST "DNS" TLS HTTP
fail=0
for host in "${hosts[@]}"; do
  cname=$(dig +short CNAME "$host" 2>/dev/null | head -1)
  addrs=$(dig +short A "$host" 2>/dev/null | tr '\n' ' ')
  dns="${cname:-$addrs}"
  [ -z "$dns" ] && dns="(no record)"

  issuer=$(echo | timeout 15 openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null \
    | openssl x509 -noout -issuer 2>/dev/null | sed 's/^issuer=//')
  case "$issuer" in
    *Google*Trust*) tls="google" ;;
    *Cloudflare*|*WE1*|*E1*) tls="cloudflare" ;;
    "") tls="-" ;;
    *) tls="$issuer" ;;
  esac

  code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -L "https://$host/" 2>/dev/null || true)
  [ -z "$code" ] && code="000"
  [ "$code" != "200" ] && fail=1

  printf '%-30s %-46s %-10s %s\n' "$host" "$dns" "$tls" "$code"

  case "$cname" in
    ghs.googlehosted.com.*) : ;;
    "") echo "    -> no DNS record yet: add the CNAME from the deploy job summary" ;;
    *) echo "    -> CNAME does not point at ghs.googlehosted.com (Cloudflare proxy on? set DNS only)" ;;
  esac
  if [ "$tls" = "cloudflare" ]; then
    echo "    -> certificate is Cloudflare's: the record is proxied and must be set to DNS only"
  fi
done

exit "$fail"
