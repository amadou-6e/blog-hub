#!/bin/sh
set -eu

python /experiment/skyvern_1_0_50_schema_workaround.py &
exec /app/entrypoint-skyvern.sh
