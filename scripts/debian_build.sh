#!/bin/sh
set -e

git config --global --add safe.directory /uno

cd /uno

make tarball

debuild

mkdir -p debian-dist

mv -v \
 ../uno*.deb \
 ../uno*.debian.tar.xz \
 ../uno*.dsc \
 ../uno*.changes \
 ../uno*.orig.tar.xz \
 ./debian-dist/
