FROM python:3.13-slim-bookworm
LABEL qfbench2.interface_version="2.0" qfbench2.track="forecasting" qfbench2.verb="forecast"
LABEL org.opencontainers.image.source="https://github.com/hhwolf/agenthon" org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
ARG DEFAULT_FORECASTER=numeric_v1_1
ENV T2_DEFAULT_FORECASTER=${DEFAULT_FORECASTER}
WORKDIR /app
COPY requirements-runtime.txt /app/requirements-runtime.txt
RUN pip install -r requirements-runtime.txt
COPY LICENSE /app/LICENSE
COPY t2agent /app/t2agent
RUN printf '#!/bin/sh\nexec python -m t2agent.cli "$@"\n' > /usr/local/bin/forecast \
    && chmod +x /usr/local/bin/forecast \
    && useradd --create-home --uid 1000 runner
USER runner
CMD ["forecast", "--help"]
