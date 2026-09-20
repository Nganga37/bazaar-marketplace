FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# The FastAPI app serves the frontend from ../frontend.
COPY backend /app/backend
COPY frontend /app/frontend

# Keep mutable SQLite data outside the application image.
RUN mkdir -p /data
ENV DATABASE_PATH=/data/bazaar.db

WORKDIR /app/backend
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
