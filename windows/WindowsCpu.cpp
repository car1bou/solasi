#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#ifdef _WIN32
#include <intrin.h>
#endif

constexpr uint32_t leaf1 = (1u<<12)|(1u<<19)|(1u<<20)|(1u<<22)|(1u<<23)|(1u<<26)|(1u<<27)|(1u<<28)|(1u<<29);
constexpr uint32_t leaf7 = (1u<<3)|(1u<<5)|(1u<<8);
constexpr uint32_t extended = 1u<<5;

bool compatible(uint32_t ecx, uint32_t ebx, uint32_t ext_ecx, uint64_t xcr0) {
    // MSVC /arch:AVX2 can also emit BMI, MOVBE, POPCNT and LZCNT instructions.
    return (ecx & leaf1)==leaf1 && (ebx & leaf7)==leaf7 && (ext_ecx & extended)==extended && (xcr0 & 6)==6;
}

int main(int argc, char **argv) {
    if (argc==2 && std::strcmp(argv[1],"--self-check")==0) {
        if (!compatible(leaf1,leaf7,extended,6)) return 1;
        for (unsigned bit=0;bit<32;++bit) {
            if ((leaf1 & (1u<<bit)) && compatible(leaf1 & ~(1u<<bit),leaf7,extended,6)) return 1;
            if ((leaf7 & (1u<<bit)) && compatible(leaf1,leaf7 & ~(1u<<bit),extended,6)) return 1;
        }
        if (compatible(leaf1,leaf7,0,6)) return 1;
        for (uint64_t state : {0ull,2ull,4ull}) if (compatible(leaf1,leaf7,extended,state)) return 1;
        std::puts("{\"self_check\":true}"); return 0;
    }
#ifdef _WIN32
    int registers[4]{}; uint32_t ecx=0,ebx=0,ext_ecx=0; uint64_t xcr0=0;
    __cpuid(registers,0); const unsigned max_leaf=registers[0];
    if (max_leaf>=1) { __cpuidex(registers,1,0); ecx=registers[2]; }
    if (max_leaf>=7) { __cpuidex(registers,7,0); ebx=registers[1]; }
    __cpuid(registers,static_cast<int>(0x80000000u));
    if (static_cast<unsigned>(registers[0])>=0x80000001u) { __cpuid(registers,static_cast<int>(0x80000001u)); ext_ecx=registers[2]; }
    const uint32_t avx_state=(1u<<26)|(1u<<27)|(1u<<28);
    if ((ecx & avx_state)==avx_state) xcr0=_xgetbv(0);
    std::printf("{\"version\":1,\"avx2_compatible\":%s,\"cpuid_1_ecx\":%u,\"cpuid_7_ebx\":%u,\"cpuid_extended_ecx\":%u,\"xcr0\":%llu}\n",
                compatible(ecx,ebx,ext_ecx,xcr0)?"true":"false",ecx,ebx,ext_ecx,static_cast<unsigned long long>(xcr0));
    return 0;
#else
    return 2;
#endif
}
