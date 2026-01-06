FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgdal-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data/satellite_data

# Expose port
EXPOSE 5000

# Run the application
CMD ["python", "src/app.py"]
