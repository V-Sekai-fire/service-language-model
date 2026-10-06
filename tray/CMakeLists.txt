# SPDX-License-Identifier: MPL-2.0
cmake_minimum_required(VERSION 3.24)
project(language_model_tray LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# SDL3, static, as interactor-xr-pilot builds it.
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
set(SDL_TESTS OFF CACHE BOOL "" FORCE)
set(SDL_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SDL_INSTALL OFF CACHE BOOL "" FORCE)
include(FetchContent)
FetchContent_Declare(SDL3 GIT_REPOSITORY https://github.com/libsdl-org/SDL.git GIT_TAG release-3.4.8 GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(SDL3)

add_executable(language-model-tray WIN32 src/main.cpp src/Tray.cpp)
target_include_directories(language-model-tray PRIVATE include)
target_link_libraries(language-model-tray PRIVATE SDL3::SDL3-static ws2_32 shell32)
add_custom_command(TARGET language-model-tray POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_CURRENT_SOURCE_DIR}/resources $<TARGET_FILE_DIR:language-model-tray>/resources)
