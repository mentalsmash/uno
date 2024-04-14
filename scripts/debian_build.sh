#!/bin/sh
set -e

git config --global --add safe.directory /uno

cd /uno

make tarball

debuild

mv -v ../uno_*.deb /uno/
