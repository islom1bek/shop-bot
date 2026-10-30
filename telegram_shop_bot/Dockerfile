FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
RUN useradd -m bot && mkdir -p /app/logs && chown -R bot /app
USER bot
CMD ["python", "bot.py"]
