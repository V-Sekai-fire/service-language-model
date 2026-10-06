// SPDX-License-Identifier: MPL-2.0

#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include <windows.h>

#include "lmtray/Tray.h"

int main(int, char**)
{
    // One tray at a time.
    HANDLE instance = CreateMutexW(nullptr, FALSE, L"Local\\LanguageModelTray");
    if (GetLastError() == ERROR_ALREADY_EXISTS)
        return 0;
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO))
        return 1;
    {
        Tray tray;
        if (!tray.ok())
            return 1;
        SDL_Event e;
        for (;;)
        {
            if (SDL_WaitEventTimeout(&e, 2000) && e.type == SDL_EVENT_QUIT)
                break;
            tray.poll();
        }
    }
    SDL_Quit();
    CloseHandle(instance);
    return 0;
}
