FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8081 HOST=0.0.0.0 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY --chown=10001:10001 . .
USER 10001:10001
EXPOSE 8081
CMD ["python", "microservices.py"]
