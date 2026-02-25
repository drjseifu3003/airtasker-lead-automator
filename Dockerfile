# Use the official Playwright Python image — has Chromium + all deps pre-baked.
# Version must match the playwright pin in requirements.txt (1.42.0).
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

# Install Python deps (Playwright browser is already in the base image)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create writable dirs for logs and session storage
RUN mkdir -p logs .playwright_storage

# Dashboard port
EXPOSE 8000

CMD ["python", "main.py"]
