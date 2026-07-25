"""PlatformIO post-build script: verify ULP data area doesn't overlap RTC slow sections."""
Import("env")

import re
import os

# The official espressif32 espidf builder doesn't emit a map file by itself
# (pioarduino did) — request one so the check below has input. Duplicate -Map
# flags are harmless (last one wins).
env.Append(LINKFLAGS=["-Wl,-Map,%s" % os.path.join(env.subst("$BUILD_DIR"), "firmware.map")])

# RTC slow memory sections that contain user data (exclude system-reserved sections)
RTC_SECTIONS = {'.rtc.data', '.rtc.bss', '.rtc_noinit', '.rtc.force_slow'}

_already_ran = [False]

def check_ulp_rtc_overlap(source, target, env):
    # ULP_DATA_BASE is only used by ULP FSM (ESP32-E), not LP core (C6).
    mcu = env.BoardConfig().get("build.mcu", "")
    if mcu != "esp32":
        return
    if _already_ran[0]:  # both post-action hooks can fire in one build
        return
    _already_ran[0] = True

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

    # Count the shared variables so the upper bound below covers the whole ULP
    # data area, not just its base. ULP_VAR_COUNT terminates the enum.
    ulp_var_count = 0
    in_enum = False
    with open(ulp_header) as f:
        for line in f:
            if line.startswith("enum ulp_var_offset"):
                in_enum = True
                continue
            if in_enum:
                if line.startswith("}"):
                    break
                if re.match(r'\s+ULP_VAR_\w+', line):
                    ulp_var_count += 1
    ulp_var_count = max(ulp_var_count - 1, 0)  # drop the ULP_VAR_COUNT terminator

    ulp_data_addr = 0x50000000 + ulp_data_base * 4

    # Find the highest end address across RTC slow memory user data sections.
    # Map file format varies: some sections have name+addr on one line,
    # others have the name on one line and addr on the next (indented).
    # IDF parks its own retain_mem_t at the top of RTC slow memory; the ULP data
    # area has to fit between the app's sections and that.
    reserved_start = 0
    rtc_end = 0
    pending_section = None
    with open(map_file) as f:
        for line in f:
            m = re.match(r'\s+(0x5[0-9a-f]+)\s+_rtc_slow_reserved_start\b', line)
            if m:
                reserved_start = int(m.group(1), 16)
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

    ulp_data_end = ulp_data_addr + ulp_var_count * 4
    if reserved_start and ulp_data_end > reserved_start:
        raise RuntimeError(
            "\n\n*** ULP data area (words %d..%d) runs past IDF's reserved "
            "RTC area at 0x%08X (word %d). Lower ULP_DATA_BASE or shrink "
            "ulp_var_offset. ***\n"
            % (ulp_data_base, ulp_data_base + ulp_var_count,
               reserved_start, (reserved_start - 0x50000000) // 4))

    # Headroom is printed every build: it has been as low as 60 bytes, and the
    # only symptom of running out is the ULP silently scribbling on RTC state.
    print("ULP/RTC overlap check: OK (RTC sections end at word %d, ULP data "
          "words %d..%d, headroom %d bytes below / %d above)"
          % (rtc_end_word, ulp_data_base, ulp_data_base + ulp_var_count,
             ulp_data_addr - rtc_end,
             (reserved_start - ulp_data_end) if reserved_start else -1))

# Both hooks: "buildprog" fires under the arduino builder, the .bin artifact
# path under the espidf builder (which doesn't trigger the alias post-action).
env.AddPostAction("buildprog", check_ulp_rtc_overlap)
env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", check_ulp_rtc_overlap)
