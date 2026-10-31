# CraftMesh 1724 —— 单进程演示镜像（纯 Python 标准库，无第三方依赖）
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

COPY . .

EXPOSE 8787

# 数据落在容器内 /app/data（SQLite），可用 -v 挂载持久化
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787"]
