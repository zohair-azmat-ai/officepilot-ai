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

COPY app/         ./app/
COPY templates/   ./templates/
COPY data/        ./data/
COPY static/      ./static/
COPY run_prod.py  .

# Hugging Face Spaces exposes port 7860
ENV APP_HOST=0.0.0.0
ENV APP_PORT=7860
ENV QUOTATION_BASE_PATH=/app/output

RUN mkdir -p /app/output

EXPOSE 7860

CMD ["python", "run_prod.py"]
