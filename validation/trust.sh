#!/bin/sh
set -eu
if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/bloghub-validation.crt
  update-ca-certificates >/dev/null
  mkdir -p /root/.pki/nssdb
  if [ ! -f /root/.pki/nssdb/cert9.db ]; then
    certutil -N --empty-password -d sql:/root/.pki/nssdb
  fi
  certutil -A -d sql:/root/.pki/nssdb -n bloghub-validation -t 'C,,' -i /certs/ca.crt
fi
exec "$@"
