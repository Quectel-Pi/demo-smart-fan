cmake_minimum_required(VERSION 3.16)
project(fan_vision LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

get_filename_component(PROJECT_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(VENDOR_ROOT "${PROJECT_ROOT}/vision/vendor/monitor_box")
set(DEFAULT_SYSROOT "${PROJECT_ROOT}/prebuilds/sysroot")
set(DEFAULT_RKNN_INCLUDE "${PROJECT_ROOT}/third_party/rknn/include")
if(NOT CMAKE_SYSROOT AND EXISTS "${DEFAULT_SYSROOT}")
    set(CMAKE_SYSROOT "${DEFAULT_SYSROOT}")
endif()

set(RKNN_INCLUDE_DIR "${DEFAULT_RKNN_INCLUDE}" CACHE PATH "Directory containing rknn_api.h")
if(NOT EXISTS "${RKNN_INCLUDE_DIR}/rknn_api.h")
    message(FATAL_ERROR "rknn_api.h not found in ${RKNN_INCLUDE_DIR}")
endif()

find_library(RKNNRT_LIB NAMES rknnrt PATHS "${CMAKE_SYSROOT}/usr/lib" NO_DEFAULT_PATH)
find_library(RGA_LIB NAMES rga PATHS "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu"
             "${CMAKE_SYSROOT}/usr/lib" NO_DEFAULT_PATH)
find_library(MPP_LIB NAMES rockchip_mpp PATHS "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu"
             "${CMAKE_SYSROOT}/usr/lib" NO_DEFAULT_PATH)
find_library(JPEG_LIB NAMES jpeg PATHS "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu"
             "${CMAKE_SYSROOT}/usr/lib" NO_DEFAULT_PATH)
find_package(Threads REQUIRED)
if(NOT RKNNRT_LIB OR NOT RGA_LIB OR NOT MPP_LIB OR NOT JPEG_LIB)
    message(FATAL_ERROR "missing one of rknnrt/rga/mpp/jpeg libraries in ${CMAKE_SYSROOT}")
endif()

add_executable(fan_vision
    fan_vision.cpp
    "${VENDOR_ROOT}/infer/jpeg_io.cpp"
    "${VENDOR_ROOT}/infer/preprocess.cpp"
    "${VENDOR_ROOT}/infer/rknn_engine.cpp"
    "${VENDOR_ROOT}/infer/yolo_post.cpp"
    "${VENDOR_ROOT}/video/mpp_jpeg_decoder.cpp"
    "${VENDOR_ROOT}/video/v4l2_source.cpp"
)
target_include_directories(fan_vision PRIVATE
    "${VENDOR_ROOT}"
    "${RKNN_INCLUDE_DIR}"
)
target_compile_options(fan_vision PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(fan_vision PRIVATE
    "${RKNNRT_LIB}" "${RGA_LIB}" "${MPP_LIB}" "${JPEG_LIB}" Threads::Threads
)
