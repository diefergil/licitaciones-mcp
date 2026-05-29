ARG PGVECTOR_IMAGE=pgvector/pgvector:pg18
FROM ${PGVECTOR_IMAGE}

ARG PG_TEXTSEARCH_VERSION=v1.2.0
ARG PG_TEXTSEARCH_SHA256=f2f0121e38ede58e92d00f12b9ee514aff654917ccaa5938a263ac4fa12d6b11

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        postgresql-server-dev-${PG_MAJOR}; \
    curl -fsSL \
        "https://github.com/timescale/pg_textsearch/archive/refs/tags/${PG_TEXTSEARCH_VERSION}.tar.gz" \
        -o /tmp/pg_textsearch.tar.gz; \
    echo "${PG_TEXTSEARCH_SHA256}  /tmp/pg_textsearch.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/pg_textsearch; \
    tar -xzf /tmp/pg_textsearch.tar.gz -C /tmp/pg_textsearch --strip-components=1; \
    make -C /tmp/pg_textsearch PG_CONFIG="/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config"; \
    make -C /tmp/pg_textsearch PG_CONFIG="/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config" install; \
    apt-get purge -y --auto-remove build-essential curl postgresql-server-dev-${PG_MAJOR}; \
    rm -rf /var/lib/apt/lists/* /tmp/pg_textsearch /tmp/pg_textsearch.tar.gz

CMD ["postgres", "-c", "shared_preload_libraries=pg_textsearch"]
