# Gunakan Python 3.10 sebagai base image
FROM python:3.10-slim

# Set working directory di container
WORKDIR /app

# Install dependensi sistem (jika diperlukan)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements terlebih dahulu untuk caching layer
COPY requirements.txt .

# Install dependencies Python
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh kode aplikasi
COPY . .

# Command untuk menjalankan bot
CMD ["python", "main.py"]