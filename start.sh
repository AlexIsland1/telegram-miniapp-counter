#!/usr/bin/env bash
# Start script for Render

gunicorn -c gunicorn.conf.py webapp.app:app