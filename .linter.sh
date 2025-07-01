#!/bin/bash
cd /home/kavia/workspace/code-generation/storeinventorypro-1045-63ce8824/inventory_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

