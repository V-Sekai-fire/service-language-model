# SPDX-License-Identifier: MPL-2.0
cmake_minimum_required(VERSION 3.24)
project(language_model_tray LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(LM_RELEASE_TAG "" CACHE STRING "GitHub release tag embedded in the setup executable")
if(NOT LM_RELEASE_TAG STREQUAL "" AND NOT LM_RELEASE_TAG MATCHES "^dev\\.[A-Za-z0-9.-]+$")
    message(FATAL_ERROR "LM_RELEASE_TAG must be empty or use the dev.* release tag format")
endif()
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

# SDL3, static, as interactor-xr-pilot builds it.
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
set(SDL_TESTS OFF CACHE BOOL "" FORCE)
set(SDL_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SDL_INSTALL OFF CACHE BOOL "" FORCE)
include(FetchContent)

if(WIN32)
    # SDL3, static, as interactor-xr-pilot builds it.
    set(SDL_SHARED OFF CACHE BOOL "" FORCE)
    set(SDL_STATIC ON CACHE BOOL "" FORCE)
    set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
    set(SDL_TESTS OFF CACHE BOOL "" FORCE)
    set(SDL_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(SDL_INSTALL OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(SDL3 GIT_REPOSITORY https://github.com/libsdl-org/SDL.git GIT_TAG release-3.4.8 GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(SDL3)

    add_executable(language-model-tray WIN32 src/main.cpp src/Tray.cpp)
    target_include_directories(language-model-tray PRIVATE include)
    target_link_libraries(language-model-tray PRIVATE SDL3::SDL3-static ws2_32 shell32)
    add_custom_command(TARGET language-model-tray POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_CURRENT_SOURCE_DIR}/resources $<TARGET_FILE_DIR:language-model-tray>/resources)

    add_executable(language-model-setup WIN32 src/install.cpp)
    target_compile_definitions(language-model-setup PRIVATE "LM_RELEASE_TAG=L\"${LM_RELEASE_TAG}\"")
    target_link_libraries(language-model-setup PRIVATE shell32 winhttp advapi32)
    target_link_options(language-model-setup PRIVATE "/MANIFESTUAC:level='requireAdministrator'")
    add_executable(payload-pack src/pack.cpp)
    target_link_libraries(language-model-tray PRIVATE bcrypt)

    if(MSVC)
        target_compile_options(language-model-setup PRIVATE /W4 /permissive-)
        target_compile_options(payload-pack PRIVATE /W4 /permissive-)
    endif()
endif()

# The portable desync installer is used by macOS releases.
add_executable(language-model-install src/install-portable.cpp)
if(WIN32)
    target_link_libraries(language-model-install PRIVATE winhttp)
endif()
