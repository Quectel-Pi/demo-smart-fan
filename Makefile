PROJECT_ROOT := $(abspath .)
BUILD_DIR ?= build
# 用项目专属变量名，避免 source build.sh 导出的全局 SYSROOT / TOOLCHAIN / QPI_SYSROOT
# 把上层 SDK 目录串进这个独立发布包的编译过程。
SMART_FAN_TOOLCHAIN ?= $(PROJECT_ROOT)/tools/cmake/aarch64-m2-debian-toolchain.cmake
SMART_FAN_SYSROOT ?= $(PROJECT_ROOT)/prebuilds/sysroot
TOOLCHAIN := $(SMART_FAN_TOOLCHAIN)
SYSROOT := $(SMART_FAN_SYSROOT)
PREBUILT_BIN ?= prebuilt/aarch64/fan_vision

.PHONY: all check-deps vision prebuilt clean test deploy run-dry web

all: vision

check-deps:
	@test -x "$(PROJECT_ROOT)/toolchains/m2-debian-rootfs-toolchain/bin/aarch64-linux-gnu-gcc" || { echo "missing project-local compiler wrapper"; exit 1; }
	@test -f "$(PROJECT_ROOT)/toolchains/m2-debian-rootfs-toolchain/bin/qemu-rootfs-tool" || { echo "missing project-local qemu wrapper"; exit 1; }
	@test -d "$(SYSROOT)" || { echo "missing project-local sysroot: $(SYSROOT)"; exit 1; }
	@test -x "$(SYSROOT)/usr/bin/aarch64-linux-gnu-gcc" || { echo "missing compiler inside sysroot: $(SYSROOT)/usr/bin/aarch64-linux-gnu-gcc"; exit 1; }
	@test -x "$(SYSROOT)/usr/libexec/gcc/aarch64-linux-gnu/14/cc1plus" || { echo "missing C++ front end in sysroot: $(SYSROOT)/usr/libexec/gcc/aarch64-linux-gnu/14/cc1plus"; exit 1; }
	@test -d "$(SYSROOT)/usr/include/c++" || { echo "missing libstdc++ headers in sysroot: $(SYSROOT)/usr/include/c++"; exit 1; }
	@test -d "$(SYSROOT)/usr/lib/linux/uapi/arm64/asm" || { echo "missing kernel uapi headers: $(SYSROOT)/usr/lib/linux/uapi/arm64/asm (asm/ headers are symlinks into it)"; exit 1; }
	@test -f "$(PROJECT_ROOT)/tools/cmake/aarch64-m2-debian-toolchain.cmake" || { echo "missing project-local CMake toolchain file"; exit 1; }
	@test -f "$(PROJECT_ROOT)/third_party/rknn/include/rknn_api.h" || { echo "missing project-local rknn_api.h"; exit 1; }
	@test -f "$(PROJECT_ROOT)/vision/vendor/monitor_box/video/v4l2_source.cpp" || { echo "missing vendored monitor_box sources"; exit 1; }
	@test -f "$(PROJECT_ROOT)/models/yolov8s-640-640.rknn" || { echo "missing project-local RKNN model"; exit 1; }
	@if command -v cmake >/dev/null 2>&1; then :; else echo "missing cmake on the host"; exit 1; fi
	@test -r /proc/sys/fs/binfmt_misc/qemu-aarch64 && grep -q '^enabled' /proc/sys/fs/binfmt_misc/qemu-aarch64 || { echo "qemu-aarch64 binfmt is not registered (install qemu-user-static)"; exit 1; }

# source build.sh 后的 SDK shell 会导出 SYSROOT/CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/QPI_SYSROOT，
# 全部指向 QPi-SDK 上层目录。这里显式丢弃这些继承变量，保证独立发布包只使用项目内的
# sysroot 和头文件，即使有人在 SDK 环境里执行 make。
vision: check-deps
	env -u SYSROOT -u QPI_SYSROOT -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS \
		cmake -S vision -B $(BUILD_DIR)/vision \
		-DCMAKE_TOOLCHAIN_FILE=$(TOOLCHAIN) \
		-DCMAKE_SYSROOT=$(SYSROOT) \
		-DCMAKE_BUILD_TYPE=Release
	env -u SYSROOT -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS \
		QPI_SYSROOT=$(SYSROOT) cmake --build $(BUILD_DIR)/vision -j

prebuilt: vision
	mkdir -p $(dir $(PREBUILT_BIN))
	cp $(BUILD_DIR)/vision/fan_vision $(PREBUILT_BIN)

test:
	python3 -m unittest discover -s tests -v

deploy:
	bash scripts/install.sh --start

web:
	adb get-state >/dev/null
	adb forward tcp:8090 tcp:8090
	@echo "Web UI: http://127.0.0.1:8090/"

run-dry:
	PYTHONPATH=app python3 -m smart_fan.main --config config/smart_fan.json --dry-run

clean:
	cmake -E remove_directory $(BUILD_DIR)
