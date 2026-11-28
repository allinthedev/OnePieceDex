#!/bin/sh
# Runs inside the throwaway container: points Django at the scratch database and hands over to the command.
# The real local database ("ballsdex") is never named here.
set -e
export BALLSDEXBOT_DB_URL="postgres://ballsdex:${POSTGRES_PASSWORD}@postgres:5432/battle_test"
exec "$@"
