FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY gateway.py .
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER 10001:10001
EXPOSE 8000
CMD ["python", "gateway.py"]
