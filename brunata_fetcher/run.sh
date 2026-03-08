#!/usr/bin/with-contenv bashio
set -e

# Token presence check without exposing secrets.
bashio::log.info "SUPERVISOR_TOKEN present: $( [ -n \"${SUPERVISOR_TOKEN:-}\" ] && echo true || echo false )"
exec python3 /app/server.py
