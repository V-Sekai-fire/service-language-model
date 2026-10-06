// SPDX-License-Identifier: MPL-2.0
//
// The language-model tray, after interactor-xr-pilot's tray/ on SDL3's tray: it starts `pixi run serve`,
// shows whether the port answers, and starts it again whenever it stops.

#pragma once

#include <SDL3/SDL.h>

#include <string>

class Tray final
{
public:
    Tray();
    ~Tray();

    Tray(const Tray&) = delete;
    Tray& operator=(const Tray&) = delete;

    bool ok() const { return tray_ != nullptr; }
    // Checks the port and restarts a stopped server; call every couple of seconds.
    void poll();

private:
    void start();
    void stop();

    static void onCopyUrl(void* userdata, SDL_TrayEntry* entry);
    static void onCopyKey(void* userdata, SDL_TrayEntry* entry);
    static void onRestart(void* userdata, SDL_TrayEntry* entry);
    static void onLogs(void* userdata, SDL_TrayEntry* entry);
    static void onQuit(void* userdata, SDL_TrayEntry* entry);

    SDL_Tray* tray_ = nullptr;
    SDL_TrayEntry* status_ = nullptr;
    SDL_Surface* idleIcon_ = nullptr;
    SDL_Surface* onlineIcon_ = nullptr;
    bool online_ = false;
    void* job_ = nullptr;
    void* process_ = nullptr;
    Uint64 startedMs_ = 0;
    std::string copiedKey_;
    Uint64 clearAtMs_ = 0;
};
