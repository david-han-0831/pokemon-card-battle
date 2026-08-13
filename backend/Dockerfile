# 포켓몬 카드 배틀 백엔드 (FastAPI + asyncpg).
FROM python:3.12-slim

WORKDIR /app

# asyncpg·pydantic 등은 wheel 이 제공되므로 빌드툴이 필요 없다.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

# 🔴 워커는 반드시 1개.
# 진행 중인 게임 상태(GameManager)가 프로세스 메모리에 있어서
# 워커가 여러 개면 같은 방이 프로세스마다 갈라진다.
# 늘리려면 먼저 상태를 Redis 같은 공유 저장소로 빼야 한다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
