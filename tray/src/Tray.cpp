// SPDX-License-Identifier: MPL-2.0

#include "lmtray/Tray.h"

#include <fstream>
#include <string>

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>

namespace
{

const char* const Url = "127.0.0.1";
const unsigned short Port = 9931;
const wchar_t* const Logs = L"logs\\serve.log";
// A server that is up in the port but not answering after this long is stuck loading; start it again.
const Uint64 StartGraceMs = 300'000;
const Uint64 ClipboardClearMs = 90'000;

bool portOpen()
{
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET)
        return false;
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(Port);
    inet_pton(AF_INET, Url, &address.sin_addr);
    const bool open = connect(s, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0;
    closesocket(s);
    return open;
}

// Read at click time, so a key `serve` generated after the tray started is still found.
std::string apiKey()
{
    std::ifstream env(".env");
    const std::string prefix = "LLAMA_API_KEY=";
    for (std::string line; std::getline(env, line);)
    {
        if (line.compare(0, prefix.size(), prefix) != 0)
            continue;
        std::string key = line.substr(prefix.size());
        const size_t first = key.find_first_not_of(" \t\"'");
        const size_t last = key.find_last_not_of(" \t\r\"'");
        return first == std::string::npos ? std::string() : key.substr(first, last - first + 1);
    }
    return {};
}

SDL_Surface* loadIcon(const char* name)
{
    const char* base = SDL_GetBasePath();
    return base != nullptr ? SDL_LoadPNG((std::string(base) + "resources/" + name).c_str()) : nullptr;
}

} // namespace

Tray::Tray()
{
    WSADATA data;
    WSAStartup(MAKEWORD(2, 2), &data);
    // Everything the server spawns dies with the tray, even if it is killed.
    job_ = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    SetInformationJobObject(job_, JobObjectExtendedLimitInformation, &limits, sizeof(limits));

    idleIcon_ = loadIcon("tray_offline.png");
    onlineIcon_ = loadIcon("tray_online.png");
    tray_ = SDL_CreateTray(idleIcon_, "Language model");
    if (tray_ == nullptr)
        return;
    SDL_TrayMenu* menu = SDL_CreateTrayMenu(tray_);
    status_ = SDL_InsertTrayEntryAt(menu, -1, "Starting", SDL_TRAYENTRY_BUTTON | SDL_TRAYENTRY_DISABLED);
    SDL_InsertTrayEntryAt(menu, -1, nullptr, 0);
    SDL_SetTrayEntryCallback(SDL_InsertTrayEntryAt(menu, -1, "Copy URL", SDL_TRAYENTRY_BUTTON), &Tray::onCopyUrl, this);
    SDL_SetTrayEntryCallback(SDL_InsertTrayEntryAt(menu, -1, "Copy API key", SDL_TRAYENTRY_BUTTON), &Tray::onCopyKey, this);
    SDL_InsertTrayEntryAt(menu, -1, nullptr, 0);
    SDL_SetTrayEntryCallback(SDL_InsertTrayEntryAt(menu, -1, "Restart server", SDL_TRAYENTRY_BUTTON), &Tray::onRestart, this);
    SDL_SetTrayEntryCallback(SDL_InsertTrayEntryAt(menu, -1, "Open logs", SDL_TRAYENTRY_BUTTON), &Tray::onLogs, this);
    SDL_InsertTrayEntryAt(menu, -1, nullptr, 0);
    SDL_SetTrayEntryCallback(SDL_InsertTrayEntryAt(menu, -1, "Quit", SDL_TRAYENTRY_BUTTON), &Tray::onQuit, this);
    poll();
}

Tray::~Tray()
{
    stop();
    if (tray_ != nullptr)
        SDL_DestroyTray(tray_);
    SDL_DestroySurface(idleIcon_);
    SDL_DestroySurface(onlineIcon_);
    CloseHandle(job_);
    WSACleanup();
}

void Tray::start()
{
    CreateDirectoryW(L"logs", nullptr);
    SECURITY_ATTRIBUTES inherit{sizeof(inherit), nullptr, TRUE};
    HANDLE log = CreateFileW(Logs, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, &inherit, OPEN_ALWAYS,
                             FILE_ATTRIBUTE_NORMAL, nullptr);
    HANDLE nul = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &inherit, OPEN_EXISTING, 0, nullptr);
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = nul;
    startup.hStdOutput = log;
    startup.hStdError = log;
    PROCESS_INFORMATION info{};
    std::wstring line = L"pixi run serve";
    if (CreateProcessW(nullptr, line.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, nullptr,
                       &startup, &info))
    {
        AssignProcessToJobObject(job_, info.hProcess);
        ResumeThread(info.hThread);
        CloseHandle(info.hThread);
        process_ = info.hProcess;
        startedMs_ = SDL_GetTicks();
    }
    CloseHandle(log);
    CloseHandle(nul);
}

void Tray::stop()
{
    TerminateJobObject(job_, 1);
    if (process_ != nullptr)
        CloseHandle(process_);
    process_ = nullptr;
}

void Tray::poll()
{
    if (tray_ == nullptr)
        return;
    // The copied key leaves the clipboard after a while, unless something else was copied since.
    if (!copiedKey_.empty() && SDL_GetTicks() >= clearAtMs_)
    {
        char* text = SDL_GetClipboardText();
        if (text != nullptr && copiedKey_ == text)
            SDL_ClearClipboardData();
        SDL_free(text);
        copiedKey_.clear();
    }
    const bool online = portOpen();
    const bool running = process_ != nullptr && WaitForSingleObject(process_, 0) == WAIT_TIMEOUT;
    // A server someone else started is adopted, not duplicated.
    if (!online && (!running || SDL_GetTicks() - startedMs_ > StartGraceMs))
    {
        stop();
        start();
    }
    const char* status = online ? "Online" : "Starting";
    SDL_SetTrayEntryLabel(status_, status);
    SDL_SetTrayTooltip(tray_, (std::string("Language model: ") + status).c_str());
    if (online != online_ && (online ? onlineIcon_ : idleIcon_) != nullptr)
        SDL_SetTrayIcon(tray_, online ? onlineIcon_ : idleIcon_);
    online_ = online;
}

void Tray::onCopyUrl(void*, SDL_TrayEntry*)
{
    SDL_SetClipboardText((std::string("http://") + Url + ":" + std::to_string(Port) + "/v1").c_str());
}

void Tray::onCopyKey(void* userdata, SDL_TrayEntry*)
{
    Tray* self = static_cast<Tray*>(userdata);
    const std::string key = apiKey();
    if (key.empty())
        SDL_SetTrayTooltip(self->tray_, "Language model: no API key in .env yet");
    else
    {
        SDL_SetClipboardText(key.c_str());
        self->copiedKey_ = key;
        self->clearAtMs_ = SDL_GetTicks() + ClipboardClearMs;
    }
}

void Tray::onRestart(void* userdata, SDL_TrayEntry*)
{
    Tray* self = static_cast<Tray*>(userdata);
    self->stop();
    self->start();
}

void Tray::onLogs(void*, SDL_TrayEntry*)
{
    ShellExecuteW(nullptr, L"open", Logs, nullptr, nullptr, SW_SHOWNORMAL);
}

void Tray::onQuit(void*, SDL_TrayEntry*)
{
    SDL_Event quit{};
    quit.type = SDL_EVENT_QUIT;
    SDL_PushEvent(&quit);
}
