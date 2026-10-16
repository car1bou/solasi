#pragma once
#include <cstdint>
#include <istream>
#include <ostream>
#include <string>

namespace solasi {
constexpr uint32_t max_frame_bytes = 100000;
enum class FrameStatus { ok, eof, truncated, oversize };
enum class TextStatus { valid, empty, invalid };

inline FrameStatus read_frame(std::istream &input, std::string &data) {
    unsigned char header[4];
    input.read(reinterpret_cast<char *>(header), 4);
    if (input.gcount() == 0 && input.eof()) return FrameStatus::eof;
    if (input.gcount() != 4) return FrameStatus::truncated;
    uint32_t size = (uint32_t(header[0]) << 24) | (uint32_t(header[1]) << 16) |
                    (uint32_t(header[2]) << 8) | header[3];
    if (size > max_frame_bytes) return FrameStatus::oversize;
    data.assign(size, '\0');
    if (size) {
        input.read(data.data(), size);
        if (input.gcount() != size) return FrameStatus::truncated;
    }
    return FrameStatus::ok;
}

inline bool write_frame(std::ostream &output, const std::string &data) {
    if (data.size() > max_frame_bytes) return false;
    uint32_t size = uint32_t(data.size());
    const unsigned char header[] = {uint8_t(size >> 24), uint8_t(size >> 16), uint8_t(size >> 8), uint8_t(size)};
    output.write(reinterpret_cast<const char *>(header), 4);
    output.write(data.data(), data.size());
    output.flush();
    return bool(output);
}

inline TextStatus text_status(const std::string &text) {
    bool nonspace = false;
    for (size_t i = 0; i < text.size();) {
        auto first = uint8_t(text[i++]);
        uint32_t code = first; int extra = 0; uint32_t minimum = 0;
        if (first >= 0xc2 && first <= 0xdf) { code = first & 0x1f; extra = 1; minimum = 0x80; }
        else if (first >= 0xe0 && first <= 0xef) { code = first & 0x0f; extra = 2; minimum = 0x800; }
        else if (first >= 0xf0 && first <= 0xf4) { code = first & 0x07; extra = 3; minimum = 0x10000; }
        else if (first >= 0x80) return TextStatus::invalid;
        if (text.size() - i < size_t(extra)) return TextStatus::invalid;
        for (int j = 0; j < extra; j++) {
            auto next = uint8_t(text[i++]);
            if ((next & 0xc0) != 0x80) return TextStatus::invalid;
            code = (code << 6) | (next & 0x3f);
        }
        if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return TextStatus::invalid;
        bool space = (code >= 9 && code <= 13) || (code >= 0x1c && code <= 0x20) ||
            code == 0x85 || code == 0xa0 || code == 0x1680 || (code >= 0x2000 && code <= 0x200a) ||
            code == 0x2028 || code == 0x2029 || code == 0x202f || code == 0x205f || code == 0x3000;
        nonspace |= !space;
    }
    return nonspace ? TextStatus::valid : TextStatus::empty;
}
}
