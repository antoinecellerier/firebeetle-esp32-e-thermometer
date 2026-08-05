"""PlatformIO post script: build-time check that the ULP FSM program fits.

The ESP32-E ULP program is assembled at runtime from ulp_insn_t macro arrays
(HULP — no ULP toolchain), so an oversized program is normally only caught
on-device (ESP_ERR_ULP_SIZE_TOO_BIG). This script computes the exact word
count at build time by running the real cross-preprocessor over the program
sources with the build's own include paths and defines, then counting the
expanded initializer entries:

  words = total_entries - macro_entries

where macro_entries are M_LABEL markers (resolve to nothing) and the
M_BRANCH halves of M_BL/M_BGE/M_BX (which fold into their branch insn).
This matches ulp_process_macros_and_load()'s accounting exactly.

Budget = CONFIG_ULP_COPROC_RESERVE_MEM / 4. Exceeding it fails the build.
"""
Import("env")

import os
import re
import subprocess

ULP_PROGRAM_SOURCES = [
    "src/UlpProgramBMP390L.cpp",
    "src/UlpProgramBMP58x.cpp",
]


def _flatten_defines(build_env, defines):
    args = []
    for d in defines:
        if isinstance(d, (list, tuple)):
            args.append("-D%s=%s" % (d[0], build_env.subst(str(d[1]))))
        else:
            args.append("-D%s" % d)
    return args


def _count_entries(array_text):
    """Count depth-1 initializer entries and .macro entries in the array body."""
    depth = 0
    entries = 0
    macro_entries = 0
    entry_start = None
    for i, c in enumerate(array_text):
        if c == '{':
            if depth == 0:
                entry_start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and entry_start is not None:
                entries += 1
                if '.macro' in array_text[entry_start:i]:
                    macro_entries += 1
                entry_start = None
    return entries, macro_entries


def check_ulp_size(source, target, env):
    if env.BoardConfig().get("build.mcu", "") != "esp32":
        return  # FSM ULP is ESP32-E only; LP core has a real linker

    # ULP word budget from the generated sdkconfig
    build_dir = env.subst("$BUILD_DIR")
    reserve = None
    sdkconfig = os.path.join(build_dir, "config", "sdkconfig.h")
    if os.path.isfile(sdkconfig):
        m = re.search(r"#define CONFIG_ULP_COPROC_RESERVE_MEM (\d+)",
                      open(sdkconfig).read())
        if m:
            reserve = int(m.group(1))
    if reserve is None:
        print("ULP size check: CONFIG_ULP_COPROC_RESERVE_MEM not found, skipping")
        return
    budget = reserve // 4

    # The ULP sources live in src/, and build_src_flags reach only the project's
    # own component — espidf.py clones the env and applies SRC_BUILD_FLAGS
    # there. Reading the global env alone would size a different program than
    # the build compiles, silently, with one word of slack at 127/128: the
    # macros passed that way are exactly the ones that change the count
    # (ULP_ALWAYS_WAKE swaps the whole wake body, ULP_TEMP_DELTA_THRESHOLD,
    # ULP_TEST_NO_I2C, PPK2_DEBUG_ULP_GPIO).
    src_env = env.Clone()
    src_env.ProcessFlags(env.get("SRC_BUILD_FLAGS"))

    cxx = src_env.subst("$CXX")
    args = [cxx, "-E", "-P", "-x", "c++"]
    args += ["-I%s" % src_env.subst(str(p)) for p in src_env.get("CPPPATH", [])]
    args += _flatten_defines(src_env, src_env.get("CPPDEFINES", []))

    failed = []
    for src in ULP_PROGRAM_SOURCES:
        path = os.path.join(env.subst("$PROJECT_DIR"), src)
        if not os.path.isfile(path):
            continue
        try:
            out = subprocess.run(args + [path], capture_output=True, text=True,
                                 timeout=120)
        except Exception as e:  # noqa: BLE001 - never break builds on tool issues
            print("ULP size check: preprocess failed for %s (%s), skipping" % (src, e))
            continue
        if out.returncode != 0:
            print("ULP size check: preprocess error for %s, skipping" % src)
            continue

        m = re.search(r"const\s+ulp_insn_t\s+program\s*\[\s*\]\s*=\s*\{", out.stdout)
        if not m:
            continue  # program variant compiled out (e.g. other sensor selected)
        # capture to the matching closing brace of the array
        start = m.end() - 1
        depth = 0
        end = None
        for i in range(start, len(out.stdout)):
            if out.stdout[i] == '{':
                depth += 1
            elif out.stdout[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            print("ULP size check: could not parse array in %s, skipping" % src)
            continue

        entries, macros = _count_entries(out.stdout[start + 1:end])
        words = entries - macros
        status = "OK" if words <= budget else "TOO BIG"
        print("ULP size check: %s = %d/%d words (%s)" %
              (os.path.basename(src), words, budget, status))
        if words > budget:
            failed.append((src, words))

    if failed:
        raise RuntimeError(
            "\n\n*** ULP program exceeds CONFIG_ULP_COPROC_RESERVE_MEM/4 = %d words: %s. "
            "Shrink the program or raise the reservation (mind ULP_DATA_BASE "
            "and the RTC layout check). ***\n"
            % (budget, ", ".join("%s=%d" % (os.path.basename(s), w) for s, w in failed)))


env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", check_ulp_size)
