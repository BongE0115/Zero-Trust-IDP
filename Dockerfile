FROM python:3.10-slim

WORKDIR /app

# 🔥 requirements 먼저 복사 (캐싱)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 🔥 나머지 코드 복사
COPY . .

# 🔥 포트 명시
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]