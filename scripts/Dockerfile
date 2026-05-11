FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir asyncpg python-dotenv
COPY generar_datos.py .
ENTRYPOINT ["python", "generar_datos.py"]
