# We use the official Playwright image so Chrome is pre-installed
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the browsers for Crawl4AI
RUN playwright install chromium

# Copy your code
COPY main.py .

# Run the bot
CMD ["python", "main.py"]