#!/bin/sh
# Peanuts Native Nova: Peanuts Native 0.1.9 (igawa6/peanuts-native, tag v0.1.9-1) built for the Samsung Exynos 1580
# (Galaxy A56: 1 x Cortex-A720 2.9 GHz, 3 x Cortex-A720 2.6 GHz, 4 x Cortex-A520 1.95 GHz) with CPU-side changes (patches/).
#
# The APK installs beside Peanuts Native (dev.nxnative.android.nova, "Peanuts Nova"). Its packer is the simulated one
# (-PnxPackEngine=fake): games are prepared in the official app, exported there (Export pack...) and imported here
# (Import pack...). The source is the release tag, so the official app's packs fit this host as they are.
#
# usage: build-nova.sh [peanuts-native checkout]      (Android SDK with NDK 28.2.13676358 and CMake 3.22.1 in $ANDROID_HOME, JDK 17+, python3, git)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$HERE/peanuts-native}"
TAG=v0.1.9-1
: "${ANDROID_HOME:=/opt/android-sdk}"

if [ ! -d "$SRC/.git" ]; then
   git clone https://github.com/igawa6/peanuts-native.git "$SRC"
   git -C "$SRC" checkout -q -b nova "$TAG"
   git -C "$SRC" -c user.name=nova -c user.email=nova@localhost am -q "$HERE"/patches/*.patch
fi

cd "$SRC/android/app"
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew --no-daemon -PnxApp=peanuts -PnxAppId=nova "-PnxLabel=Peanuts Nova" -PnxVersion=0.1.9 -PnxVersionCode=109 \
   -PnxPackEngine=fake -PnxCpu=cortex-a720+nosve apk
mkdir -p "$HERE/dist"
cp out/nxnative-android-peanuts.apk "$HERE/dist/peanuts-nova-0.1.9-a56.apk"
echo "built $HERE/dist/peanuts-nova-0.1.9-a56.apk"
