# Use a slim Python base image
# FROM python:3.10-slim
FROM python:3.11-slim

# Set working directory
# WORKDIR /services
WORKDIR /app

# Install system-level dependencies
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

COPY services/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your app code
# COPY . .
COPY services/ ./services/

# Expose the Flask port
EXPOSE 8000

# Start the Flask API
# CMD ["python", "services/app.py"]
CMD ["uvicorn", "services.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
