FROM python:3.11-bookworm

RUN apt-get update -y && \
    DEBIAN_FRONTEND="noninteractive" apt-get install -y sqlite3

COPY ./entrypoint.sh ./

ENTRYPOINT ["/entrypoint.sh"]
