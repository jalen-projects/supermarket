#!/usr/bin/env bash
# Writes nginx's site for supermarket.campusnect.com (the FreshWay
# demonstration shop) and reloads nginx. A copy of install_nginx.sh, which
# does the same for MAQAM - kept separate so MAQAM's is never touched.
#
# WHY A SCRIPT RATHER THAN A FILE TO COPY: the site must use the SAME HTTPS
# certificate CampusNect already has (a wildcard for *.campusnect.com), and the
# exact folder certbot put it in is on the server, not in this repository. This
# reads it out of CampusNect's own nginx site, so it cannot be mistyped.
#
# WHY IT WINS OVER CAMPUSNECT'S WILDCARD: nginx always prefers an exact
# server_name (supermarket.campusnect.com) over a wildcard one (*.campusnect.com),
# whatever order the files load in. Nothing in CampusNect's site is changed.
#
# Run as root:  bash deploy/install_nginx_demo.sh
set -euo pipefail

SITE=/etc/nginx/sites-available/smdemo
CAMPUSNECT=$(grep -l '\*\.campusnect\.com' /etc/nginx/sites-enabled/* | grep -v -e '/maqam$' -e '/smdemo$' | head -n1 || true)
if [ -z "$CAMPUSNECT" ]; then
  echo "Could not find CampusNect's nginx site - stopping, nothing changed."
  exit 1
fi
CERT=$(grep -h "^\s*ssl_certificate\s" "$CAMPUSNECT" | head -n1 | awk '{print $2}' | tr -d ';' || true)
KEY=$(grep -h "^\s*ssl_certificate_key\s" "$CAMPUSNECT" | head -n1 | awk '{print $2}' | tr -d ';' || true)

if [ -z "$CERT" ] || [ -z "$KEY" ]; then
  echo "Could not find CampusNect's certificate in $CAMPUSNECT - stopping, nothing changed."
  exit 1
fi
echo "Using the certificate CampusNect already uses: $CERT"

cat > "$SITE" <<NGINX
# FRESHWAY SUPERMARKET (DEMONSTRATION) - written by deploy/install_nginx_demo.sh
server {
    listen 80;
    server_name supermarket.campusnect.com;
    return 301 https://\$host\$request_uri;
}

server {
    # http2: one connection carries the page, its styles and its pictures
    # together. The shop is ~0.4 s from this server, so every extra
    # connection and every extra handshake is felt on each press.
    listen 443 ssl http2;
    server_name supermarket.campusnect.com;

    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    # A phone that was here a minute ago resumes the secure connection
    # instead of negotiating it again from scratch.
    ssl_session_cache   shared:SMDEMO:10m;
    ssl_session_timeout 1d;
    keepalive_timeout   75s;

    gzip on;
    gzip_vary on;
    gzip_types text/css application/javascript image/svg+xml application/json application/manifest+json;

    # Product photos and the logo are small; a backup upload is not done here.
    client_max_body_size 10M;

    location / {
        include proxy_params;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://127.0.0.1:8078;
        proxy_read_timeout 60s;
    }
}
NGINX

ln -sf "$SITE" /etc/nginx/sites-enabled/smdemo
nginx -t
systemctl reload nginx
echo "nginx now serves supermarket.campusnect.com from the demo shop system."
