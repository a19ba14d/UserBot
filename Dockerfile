FROM python:3.11-slim

WORKDIR /app

# 系统依赖: 仅保留 ca-certificates 用于 HTTPS 校验
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 先 COPY requirements 单独 layer, 利用缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY userbot/ ./userbot/

# session 持久化目录 (运行时挂载卷); session 文件 = 账号身份, 必须持久化
RUN mkdir -p /app/sessions
ENV TG_SESSION_NAME=/app/sessions/userbot

# 不缓冲日志 -> 直接输出到 docker logs
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "userbot"]
