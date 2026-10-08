FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends aapt apksigner default-jre-headless && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 parser && useradd --uid 10001 --gid parser --no-create-home parser \
    && mkdir -p /inbox /outbox && chown parser:parser /inbox /outbox
WORKDIR /parser
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/licenses/fuma/
COPY parser/parse_package.py parser/service.py ./
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["python", "-I", "/parser/service.py"]
