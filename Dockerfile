FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium
RUN apt-get update && apt-get install -y libreoffice

# Copy your script files
COPY . .

CMD ["python", "main.py"]