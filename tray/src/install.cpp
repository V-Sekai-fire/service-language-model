// Downloads release .zst assets (or reads a local folder) and restores them. No pixi, python or zstd.exe needed.
// Usage: language-model-install [--from <dir>] [--tag <tag>] [--repo <owner/name>]
#include <windows.h>
#include <winhttp.h>
#include <zstd.h>

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <regex>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static std::wstring widen(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, w.data(), n);
    w.resize(n - 1);
    return w;
}

// Streams an https URL into a sink; follows redirects (WinHTTP default).
template <class Sink> static bool httpGet(const std::string& url, Sink sink) {
    URL_COMPONENTS uc{};
    uc.dwStructSize = sizeof(uc);
    wchar_t host[256], path[4096];
    uc.lpszHostName = host; uc.dwHostNameLength = 256;
    uc.lpszUrlPath = path; uc.dwUrlPathLength = 4096;
    std::wstring w = widen(url);
    if (!WinHttpCrackUrl(w.c_str(), 0, 0, &uc)) return false;
    HINTERNET s = WinHttpOpen(L"language-model-install", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, nullptr, nullptr, 0);
    HINTERNET c = WinHttpConnect(s, host, uc.nPort, 0);
    HINTERNET r = WinHttpOpenRequest(c, L"GET", path, nullptr, nullptr, nullptr, uc.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0);
    bool ok = WinHttpSendRequest(r, L"Accept: application/vnd.github+json\r\n", (DWORD)-1, nullptr, 0, 0, 0) && WinHttpReceiveResponse(r, nullptr);
    DWORD code = 0, len = sizeof(code);
    if (ok) WinHttpQueryHeaders(r, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr, &code, &len, nullptr);
    ok = ok && code == 200;
    std::vector<char> buf(1 << 20);
    DWORD got;
    while (ok && WinHttpReadData(r, buf.data(), (DWORD)buf.size(), &got) && got) sink(buf.data(), got);
    WinHttpCloseHandle(r); WinHttpCloseHandle(c); WinHttpCloseHandle(s);
    return ok;
}

static bool decompressInto(const fs::path& zst, std::ofstream& out) {
    std::ifstream in(zst, std::ios::binary);
    ZSTD_DCtx* d = ZSTD_createDCtx();
    std::vector<char> ib(ZSTD_DStreamInSize()), ob(ZSTD_DStreamOutSize());
    bool ok = true;
    while (ok && in) {
        in.read(ib.data(), ib.size());
        ZSTD_inBuffer i{ib.data(), (size_t)in.gcount(), 0};
        while (i.pos < i.size) {
            ZSTD_outBuffer o{ob.data(), ob.size(), 0};
            if (ZSTD_isError(ZSTD_decompressStream(d, &o, &i))) { ok = false; break; }
            out.write(ob.data(), o.pos);
        }
    }
    ZSTD_freeDCtx(d);
    return ok && out.good();
}

int main(int argc, char** argv) {
    std::string from, tag = "v0.5.0-dev.2", repo = "V-Sekai-fire/service-language-model";
    for (int i = 1; i + 1 < argc; i += 2) {
        std::string a = argv[i];
        (a == "--from" ? from : a == "--tag" ? tag : repo) = argv[i + 1];
    }
    if (from.empty()) {
        from = "dist";
        fs::create_directories(from);
        std::string json;
        if (!httpGet("https://api.github.com/repos/" + repo + "/releases/tags/" + tag, [&](const char* p, DWORD n) { json.append(p, n); })) {
            std::fprintf(stderr, "cannot fetch release %s\n", tag.c_str());
            return 1;
        }
        std::regex re(R"x("browser_download_url"\s*:\s*"([^"]+\.zst(?:\.\d{3})?)")x");
        for (std::sregex_iterator it(json.begin(), json.end(), re), end; it != end; ++it) {
            std::string url = (*it)[1], name = url.substr(url.rfind('/') + 1);
            std::printf("download %s\n", name.c_str());
            std::ofstream f(fs::path(from) / name, std::ios::binary);
            if (!httpGet(url, [&](const char* p, DWORD n) { f.write(p, n); })) { std::fprintf(stderr, "failed: %s\n", name.c_str()); return 1; }
        }
    }
    std::regex zre(R"((.+)\.zst(\.\d{3})?$)");
    std::map<std::string, std::vector<fs::path>> groups;
    for (auto& e : fs::directory_iterator(from)) {
        std::smatch m;
        std::string n = e.path().filename().string();
        if (std::regex_match(n, m, zre)) groups[m[1]].push_back(e.path());
    }
    for (auto& [name, parts] : groups) {
        std::sort(parts.begin(), parts.end());
        std::string rel = std::regex_replace(name, std::regex("__"), "/");
        fs::path dest = rel;
        if (dest.has_parent_path()) fs::create_directories(dest.parent_path());
        std::ofstream out(dest, std::ios::binary);
        for (auto& p : parts)
            if (!decompressInto(p, out)) { std::fprintf(stderr, "failed: %s\n", p.string().c_str()); return 1; }
        std::printf("%s\n", rel.c_str());
    }
    return 0;
}
