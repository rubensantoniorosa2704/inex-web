FROM python:3.13-slim AS base

# Sem bytecode solto, logs imediatos
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependências primeiro (cache de layer)
COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    rm -rf /root/.cache

# Copiar código e dados
COPY inex_web/ inex_web/
COPY data/ data/

# Usuário não-root
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

# Produção: gunicorn com workers conservadores (256MB RAM no Fly free tier)
CMD ["gunicorn", "inex_web.app:app", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
