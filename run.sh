#!/bin/bash
# Simple script to run the MachView Flask application

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run the Flask application
python src/app.py

