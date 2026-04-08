"""PlatformIO post-build script: verify ULP data area doesn't overlap RTC slow sections."""
Import("env")

import re
import os

# RTC slow memory sections that contain user data (exclude system-reserved sections)
RTC_SECTIONS = {'.rtc.data', '.rtc.bss', '.rtc_noinit', '.rtc.force_slow'}

def check_ulp_rtc_overlap(source, target, env):
    build_dir = env.subst("$BUILD_DIR")
    map_file = os.path.join(build_dir, "firmware.map")
    if not os.path.isfile(map_file):
        print("WARNING: firmware.map not found at %s, skipping ULP/RTC overlap check" % map_file)
        return

    # Parse ULP_DATA_BASE from UlpProgram.h
    project_dir = env.subst("$PROJECT_DIR")
    ulp_header = os.path.join(project_dir, "include", "UlpProgram.h")
    ulp_data_base = None
    if os.path.isfile(ulp_header):
        with open(ulp_header) as f:
            for line in f:
                m = re.match(r'#define\s+ULP_DATA_BASE\s+(\d+)', line)
                if m:
                    ulp_data_base = int(m.group(1))
                    break
    if ulp_data_base is None:
        return  # no ULP in this build

    ulp_data_addr = 0x50000000 + ulp_data_base * 4

    # Find the highest end address across RTC slow memory user data sections.
    # Map file format varies: some sections have name+addr on one line,
    # others have the name on one line and addr on the next (indented).
    rtc_end = 0
    pending_section = None
    with open(map_file) as f:
        for line in f:
            # Single-line: ".rtc.data  0x50000200  0x18ec"
            m = re.match(r'^(\S+)\s+(0x5[0-9a-f]+)\s+(0x[0-9a-f]+)', line)
            if m and m.group(1) in RTC_SECTIONS:
                sec_end = int(m.group(2), 16) + int(m.group(3), 16)
                if sec_end > rtc_end:
                    rtc_end = sec_end
                pending_section = None
                continue

            # Multi-line: section name on its own line
            stripped = line.strip()
            if stripped in RTC_SECTIONS:
                pending_section = stripped
                continue

            # Continuation: "                0x50001aec  0x84"
            if pending_section:
                m = re.match(r'^\s+(0x5[0-9a-f]+)\s+(0x[0-9a-f]+)', line)
                if m:
                    sec_end = int(m.group(1), 16) + int(m.group(2), 16)
                    if sec_end > rtc_end:
                        rtc_end = sec_end
                pending_section = None

    if rtc_end == 0:
        return  # no RTC sections found

    rtc_end_word = (rtc_end - 0x50000000 + 3) // 4
    if ulp_data_addr < rtc_end:
        raise RuntimeError(
            "\n\n*** ULP_DATA_BASE (%d, addr 0x%08X) "
            "overlaps RTC slow sections (end 0x%08X, word %d). "
            "Increase ULP_DATA_BASE to at least %d. ***\n"
            % (ulp_data_base, ulp_data_addr, rtc_end, rtc_end_word, rtc_end_word + 1))

    print("ULP/RTC overlap check: OK "
          "(ULP data at word %d, RTC sections end at word %d)"
          % (ulp_data_base, rtc_end_word))

env.AddPostAction("buildprog", check_ulp_rtc_overlap)
