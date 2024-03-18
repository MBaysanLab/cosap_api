#!/bin/bash
chown -R postgres:postgres /var/lib/postgresql/data
exec "$@"
