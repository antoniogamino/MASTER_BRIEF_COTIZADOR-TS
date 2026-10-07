FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e . && python scripts/make_sample_data.py
ENV TSQ_DATABASE_URL=sqlite:////app/data/tsq.db
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn ts_quoter.api.main:app --host 0.0.0.0 --port 8000"]
