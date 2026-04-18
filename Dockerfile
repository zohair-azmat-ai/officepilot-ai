# ── Hugging Face Spaces / Docker deployment ───────────────────────────────────
# Exposes the FastAPI backend on port 7860 (HF Spaces standard).
# The Telegram bot starts automatically if TELEGRAM_ENABLED=true is set
# as a Space secret.
#
# Note: Excel/PDF output paths must be set to writable container paths.
# Set QUOTATION_BASE_PATH=/app/output in your Space secrets.

FROM python:3.11-slim

WORKDIR /app

# Install LibreOffice for PDF export (optional — remove if not needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/              ./app/
COPY data/             ./data/
COPY static/           ./static/
COPY create_template.py .
COPY run_prod.py        .

# Generate the Excel template at build time (no binary in source control)
RUN mkdir -p /app/templates /app/output && python create_template.py

# Hugging Face Spaces exposes port 7860
ENV APP_HOST=0.0.0.0
ENV APP_PORT=7860
ENV QUOTATION_BASE_PATH=/app/output

EXPOSE 7860

CMD ["python", "run_prod.py"]
