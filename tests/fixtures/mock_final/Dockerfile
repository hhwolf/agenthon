FROM python:3.13-slim-bookworm
ARG MODE=crash
ENV MOCK_FAILURE=$MODE
LABEL qfbench2.interface_version="2.0"
COPY broken.py /broken.py
ENTRYPOINT ["python", "/broken.py"]
