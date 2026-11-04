FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt requirements-listener.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-listener.txt
COPY . .
CMD ["python", "main.py"]
