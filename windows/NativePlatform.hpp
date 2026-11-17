#pragma once
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <cstdio>
#include <string>
#include <vector>

namespace solasi {
inline void binary_stdio() {
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
}
inline int utf8_main(int argc, wchar_t **argv, int (*entry)(int, char **)) {
    std::vector<std::string> strings;
    for (int i = 0; i < argc; ++i) {
        int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[i], -1, nullptr, 0, nullptr, nullptr);
        if (size <= 0) return 2;
        std::string value(size_t(size), '\0');
        WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[i], -1, value.data(), size, nullptr, nullptr);
        value.pop_back(); strings.push_back(std::move(value));
    }
    std::vector<char *> pointers;
    for (auto &value : strings) pointers.push_back(value.data());
    pointers.push_back(nullptr);
    return entry(argc, pointers.data());
}
}
#endif
