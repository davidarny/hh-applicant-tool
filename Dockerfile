FROM python:3.13-slim

# Системные зависимости
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc \
      libc6-dev \
      procps \
      cron \
      dos2unix \
      tzdata \
      less && \
    rm -rf /var/lib/apt/lists/*

# Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID docker && \
    useradd -u $UID -g docker -m -s /bin/bash docker

WORKDIR /app

COPY pyproject.toml poetry.lock* .

# 1. Копируем исходный код. С 2.0 авторизация идёт без браузера,
#    поэтому playwright и chromium больше не ставим
RUN touch README.md
COPY src ./src

# 2. Устанавливаем саму утилиту с зависимостями
#    Подготовка cron
RUN pip install --no-cache-dir -e . && \
    touch /var/log/cron.log && chown docker:docker /var/log/cron.log && \
    mkdir -p ./config && chown -R docker:docker ./config

# Копируем остальное (эти файлы мешают кешированию последующих слоев)
COPY --chmod=755 crontab startup.sh .

# Запускаем cron и читаем лог
# cron не видит переменные окружения, переданные главному процессу, точнее
# он начинает новую сессию, где тот же $CONFIG_DIR пуст
CMD printenv | grep -E 'CONFIG_DIR|HH_PROFILE_ID' >> /etc/environment && \
    chown -R docker:docker ./config && \
    dos2unix -n ./crontab /tmp/crontab && \
    crontab -u docker /tmp/crontab && \
    cron && \
    tail -f /var/log/cron.log

