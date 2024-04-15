ARG BASE_IMAGE=ubuntu:22.04
ARG PACKAGE_NAME=uno
ARG PACKAGE_VERSION=*
ARG PACKAGE_ARCH=
FROM ${BASE_IMAGE}

COPY ./debian-dist/* /tmp/debian-dist/

RUN set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt install -y /uno/debian-dist/${PACKAGE_NAME}_${PACKAGE_VERSION}_${PACKAGE_ARCH:-dpkg --print-architecture}.deb; \
    apt-get clean; \
    rm -rf /tmp/debian-tmp

ENV RTI_LICENSE_FILE "/rti_license.dat"
