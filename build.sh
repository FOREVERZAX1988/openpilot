#!/usr/bin/env bash
set -e


BUILD_DIR=/data/openpilot
cd $BUILD_DIR
git init
#git remote add origin https://github.com/ajouatom/openpilot
git remote set-url --push origin https://jihulab.com/mr-one/onepilot.git

# Cleanup
find . -name '*.a' -delete
find . -name '*.o' -delete
find . -name '*.os' -delete
find . -name '*.pyc' -delete
find . -name 'moc_*' -delete
find . -name '__pycache__' -delete
rm -rf .sconsign.dblite Jenkinsfile release/
rm selfdrive/modeld/models/*.onnx
touch prebuilt

# Add built files to git
git add -f .

VERSION="dp2026-2-1"
git commit -m $VERSION
git branch -m $VERSION
git push -f origin $VERSION
