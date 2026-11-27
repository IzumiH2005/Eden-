#!/bin/sh
# RADV Xclipse Nova: radv-xclipse v1.9.0 (JimVulkan, Mesa 27.0.0-devel) built for the
# Samsung Exynos 1580 (Galaxy A56, Xclipse 540): Cortex-A720 + Cortex-A520 (Armv9.2-A).
#
# Driver changes (patches/, all off by default): opt-in RDNA3 ISA features and the
# debug.radv_xclipse_nova profile (wave32, WGP always-on). Build differences from radv-xclipse's
# own build.sh:
#   - buildtype release (-O3) instead of debugoptimized (-O2 -g)
#   - no LTO: Mesa refuses it (meson.build: "Building Mesa with LTO is not supported")
#   - -mcpu=cortex-a720 instead of the generic -march=armv8.2-a: Armv9.2 instructions and
#     scheduling for the A56's CPU. The result only runs on Armv9.2 CPUs such as the
#     Exynos 1580's; use radv-xclipse's own build for any other phone.
#
# usage: build-nova.sh <android-ndk> [radv-xclipse checkout]
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
NDK="${1:?usage: build-nova.sh <android-ndk> [radv-xclipse checkout]}"
SRC="${2:-$HERE/radv-xclipse}"
BASE_COMMIT=cc87fdf71267dd0acc3b470920a6566a1a46f0be   # radv-xclipse v1.9.0

if [ ! -d "$SRC/.git" ]; then
   git clone https://github.com/JimVulkan/radv-xclipse.git "$SRC"
   git -C "$SRC" checkout -q "$BASE_COMMIT"
   git -C "$SRC" -c user.name=nova -c user.email=nova@localhost am -q "$HERE"/patches/*.patch
fi

BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
BUILD="$SRC/build-nova"
mkdir -p "$BUILD"
cat > "$BUILD/cross.ini" <<EOF
[binaries]
c = '$BIN/aarch64-linux-android34-clang'
cpp = '$BIN/aarch64-linux-android34-clang++'
ar = '$BIN/llvm-ar'
strip = '$BIN/llvm-strip'
[properties]
cpp_link_args = ['-static-libstdc++']
[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'
EOF

CPU_FLAGS="-mcpu=cortex-a720+nosve"   # A720 tuning and Armv9 instructions, no SVE auto-vectorisation
if [ ! -f "$BUILD/build.ninja" ]; then
   meson setup "$BUILD" "$SRC" --cross-file "$BUILD/cross.ini" \
      -Dbuildtype=release -Db_ndebug=true \
      -Dplatforms=android -Dplatform-sdk-version=34 -Dandroid-stub=true -Dandroid-strict=false \
      -Dandroid-libbacktrace=disabled \
      -Dvulkan-drivers=amd -Dgallium-drivers= -Dvulkan-layers= -Dtools= \
      -Dllvm=disabled -Dzstd=disabled -Dlmsensors=disabled -Dperfetto=false \
      -Dglx=disabled -Dgbm=disabled -Degl=disabled -Dgles1=disabled -Dgles2=disabled \
      -Dallow-fallback-for=libdrm,perfetto --force-fallback-for=expat,libdrm,zlib \
      -Dlibdrm:default_library=static -Dexpat:default_library=static -Dzlib:default_library=static \
      "-Dc_args=$CPU_FLAGS" "-Dcpp_args=$CPU_FLAGS"
fi
ninja -C "$BUILD" src/amd/vulkan/libvulkan_radeon.so
"$BIN/llvm-strip" -o "$BUILD/vulkan.radeon.so" "$BUILD/src/amd/vulkan/libvulkan_radeon.so"

MESA="$(cat "$SRC/VERSION")"
NOVA_NAME="RADV Xclipse Nova (Mesa $MESA, Exynos 1580)" \
NOVA_DESCRIPTION="radv-xclipse v1.9.0 for the Exynos 1580 / Xclipse 540 (Galaxy A56): -O3, Cortex-A720, opt-in Nova profile (debug.radv_xclipse_nova)." \
NOVA_AUTHOR="JimVulkan (radv-xclipse), EdEn.claude (Nova build)" \
NOVA_ZIP_PREFIX="radv-xclipse-nova-a56" \
python3 "$SRC/android/package.py" "$BUILD/vulkan.radeon.so" "$HERE/dist"
