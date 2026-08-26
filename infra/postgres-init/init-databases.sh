#!/usr/bin/env bash
# Runs automatically on the postgres container's FIRST startup only (standard
# docker-entrypoint-initdb.d behavior) — creates one database per microservice.
# The official postgres image has no built-in "multiple databases" env var;
# this script is the standard way to get that.
set -e

for db in chat_agent_db file_processing_db knowledge_db; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    SELECT 'CREATE DATABASE $db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
EOSQL
done
