set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

get_filename_component(TOOLS_DIR "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
get_filename_component(ROOT_DIR "${TOOLS_DIR}/.." ABSOLUTE)
set(SYSROOT "${ROOT_DIR}/prebuilds/sysroot" CACHE PATH "Project-local AArch64 sysroot")
set(TOOLCHAIN "${ROOT_DIR}/toolchains/m2-debian-rootfs-toolchain")
set(CROSS_COMPILE "aarch64-linux-gnu-")

# 本项目单独发布，只使用 demo-smart-fan 目录内的 sysroot 和工具链 wrapper。
# 项目内工具链为 Debian GCC 14/binutils 2.44，通过宿主机 qemu-aarch64 binfmt 执行。
if(NOT EXISTS "${SYSROOT}/usr/bin/${CROSS_COMPILE}gcc")
    message(FATAL_ERROR "project-local compiler missing: ${SYSROOT}/usr/bin/${CROSS_COMPILE}gcc")
endif()
if(NOT EXISTS "${TOOLCHAIN}/bin/${CROSS_COMPILE}gcc")
    message(FATAL_ERROR "project-local toolchain wrapper missing: ${TOOLCHAIN}/bin/${CROSS_COMPILE}gcc")
endif()

set(CMAKE_SYSROOT "${SYSROOT}")
set(CMAKE_C_COMPILER "${TOOLCHAIN}/bin/${CROSS_COMPILE}gcc")
set(CMAKE_CXX_COMPILER "${TOOLCHAIN}/bin/${CROSS_COMPILE}g++")
set(CMAKE_ASM_COMPILER "${TOOLCHAIN}/bin/${CROSS_COMPILE}gcc")
set(CMAKE_AR "${TOOLCHAIN}/bin/${CROSS_COMPILE}ar")
set(CMAKE_RANLIB "${TOOLCHAIN}/bin/${CROSS_COMPILE}ranlib")
set(CMAKE_STRIP "${TOOLCHAIN}/bin/${CROSS_COMPILE}strip")
set(CMAKE_NM "${TOOLCHAIN}/bin/${CROSS_COMPILE}nm")
set(CMAKE_OBJCOPY "${TOOLCHAIN}/bin/${CROSS_COMPILE}objcopy")
set(CMAKE_OBJDUMP "${TOOLCHAIN}/bin/${CROSS_COMPILE}objdump")
set(CMAKE_READELF "${TOOLCHAIN}/bin/${CROSS_COMPILE}readelf")

set(CMAKE_FIND_ROOT_PATH "${SYSROOT}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# wrapper 自己也会设置该变量；在这里固定为项目内路径，避免宿主机环境串入外部 sysroot。
set(ENV{QPI_SYSROOT} "${SYSROOT}")
set(ENV{PKG_CONFIG_SYSROOT_DIR} "${SYSROOT}")
set(ENV{PKG_CONFIG_LIBDIR} "${SYSROOT}/usr/lib/aarch64-linux-gnu/pkgconfig:${SYSROOT}/usr/share/pkgconfig:${SYSROOT}/usr/lib/pkgconfig")
