# Use the official Playwright Python image — has Chromium + all deps pre-baked.
FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

# Install VNC and noVNC in one layer, minimal packages only
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        supervisor \
        fluxbox \
    && ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create writable dirs for logs and session storage
RUN mkdir -p logs .playwright_storage

# Dashboard port (8000) and noVNC port (6080)
EXPOSE 8000 6080

# Use supervisor to run all processes
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]