FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir asyncpg python-dotenv pyyaml
COPY generar_datos.py generar_datos_restaurante.py provision_tenant.py .
ENTRYPOINT ["python", "generar_datos.py"]
