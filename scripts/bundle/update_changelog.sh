#!/bin/sh -ex
VERSION=${1:-$(head -1 debian/changelog | awk '{print $2;}' | tr -d '(' | tr -d ')')}
BUILD_CODENAME=$(. /etc/os-release && echo ${VERSION_CODENAME})
MESSAGE="${2:-Package built on ${BUILD_CODENAME}}"
TIMESTAMP=$(stat -c "%Y" debian/changelog)
debchange \
  -b \
  -v ${VERSION}${BUILD_CODENAME} \
  -p \
  -D UNRELEASED \
  -u high \
  -m \
  "${MESSAGE}"

if [ -n "${PRESERVE_TIMESTAMP}" ]; then
  touch -d @${TIMESTAMP} debian/changelog
fi
