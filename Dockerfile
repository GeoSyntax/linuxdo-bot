# linux.do 关键词监控机器人 - 容器镜像
# 主力采集源是官方 TG 频道网页版（纯 requests，无需浏览器），故用轻量 slim 镜像。
# 若你要用 --source linuxdo 直连（Playwright 过 Cloudflare 盾），改用
#   FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
# 并在 requirements 里启用 playwright。
FROM python:3.12-slim

WORKDIR /app

# requirements-bot.txt 只含机器人运行所需（requests + numpy），镜像更小
COPY requirements-bot.txt .
RUN pip install --no-cache-dir -r requirements-bot.txt

# 拷项目
COPY zhihu_crawler/ ./zhihu_crawler/
COPY linuxdo_bot/ ./linuxdo_bot/

# 数据目录（挂卷持久化订阅/去重/语料库）
VOLUME ["/app/data"]

# token 通过环境变量或挂载 .env 传入
ENV HEADLESS=true

CMD ["python", "-m", "linuxdo_bot"]
