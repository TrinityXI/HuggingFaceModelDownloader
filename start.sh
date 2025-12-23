#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Navigate to the deploy directory
cd "$SCRIPT_DIR/deploy"

echo "Starting services from deploy/docker-compose.yml..."
docker-compose up -d --build

echo "Services started."
echo "Backend API: http://localhost:8000"
echo "Frontend UI: http://localhost:3000"