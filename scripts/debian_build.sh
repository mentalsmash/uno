#!/bin/sh
set -e

git config --global --add safe.directory /uno

cd /uno

make tarball

debuild

mkdir -p debian-dist

mv -v \
 ../uno_*.deb \
 ../uno_*.debian.tar.xz \
 ../uno_*.dsc \
 ../uno_*.changes \
 ../uno_*.orig.tar.xz \
 ./debian-dist/
