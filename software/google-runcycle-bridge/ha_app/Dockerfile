FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bridge.py source.py oauth_store.py device_config.py start_app.py ./
COPY LICENSE NOTICE THIRD_PARTY.md ./
EXPOSE 8767
CMD ["python", "start_app.py"]
