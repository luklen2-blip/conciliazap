FROM python:3.12-slim

WORKDIR /usr/src/app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Instala dependencias com cache otimizado
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia o codigo-fonte
COPY . .

# Testes de integridade obrigatorios antes da inicializacao
RUN python tests/run_all.py

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
