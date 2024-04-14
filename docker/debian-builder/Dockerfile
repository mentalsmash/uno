ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get upgrade -y --no-install-recommends; \
    apt-get install -y --no-install-recommends \
      git \
      tar \
      debhelper \
      devscripts \
      build-essential \
      lintian \
      python3-dev \
      python3-venv; \
    apt-get clean
