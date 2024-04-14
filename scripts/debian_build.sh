#!/bin/sh -e

cd /uno

make tarball

debuild

mv -v ../uno_*.deb /uno/
