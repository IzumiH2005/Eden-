#!/bin/sh
# Peanuts Native Nova: Peanuts Native 0.1.9 (igawa6/peanuts-native, tag v0.1.9-1) built for the Samsung Exynos 1580
# (Galaxy A56: 1 x Cortex-A720 2.9 GHz, 3 x Cortex-A720 2.6 GHz, 4 x Cortex-A520 1.95 GHz) with CPU-side changes (patches/).
#
# The APK installs beside Peanuts Native (dev.nxnative.android.nova, "Peanuts Nova") and carries the real on-device packer
# (Build), made from the same tree by peanuts/scripts/ondevice-stage.sh. The source is the release tag and the shader library
# is unchanged, so packs made by either app fit the other.
#
# usage: build-nova.sh [peanuts-native checkout]
#   needs: Android SDK with NDK 28.2.13676358 and CMake 3.22.1 in $ANDROID_HOME, JDK 17+, python3 with fontTools, git, zsh, curl, cmake, ninja,
#   and the .NET 10 SDK on PATH (dotnet; the translator is NativeAOT for linux-bionic-arm64)
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

# The on-device packer's stage: CPython 3.14, capstone, lz4, the translator (.NET NativeAOT), SPIRV-Tools, the pack worker
STAGE="$HERE/stage-work"
[ -f "$STAGE/stage/lib/libdmsh_xlate.so" ] || ANDROID_NDK_HOME="$ANDROID_HOME/ndk/28.2.13676358" zsh "$SRC/peanuts/scripts/ondevice-stage.sh" "$STAGE" all

cd "$SRC/android/app"
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew --no-daemon -PnxApp=peanuts -PnxAppId=nova "-PnxLabel=Peanuts Nova" -PnxVersion=0.1.9 -PnxVersionCode=110 \
   -PnxPackStage="$STAGE/stage" -PnxCpu=cortex-a720+nosve apk
mkdir -p "$HERE/dist"
cp out/nxnative-android-peanuts.apk "$HERE/dist/peanuts-nova-0.1.9-a56.apk"
echo "built $HERE/dist/peanuts-nova-0.1.9-a56.apk"
