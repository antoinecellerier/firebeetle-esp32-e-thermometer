"""
PlatformIO pre-build script for compiling the ESP32-C6 LP core binary.

Uses the RISC-V toolchain and ESP-IDF sources from PlatformIO packages
to compile the LP core program. No local copies of ESP-IDF sources needed.

Headers come from pioarduino's framework-arduinoespressif32-libs package.
LP core framework sources come from the framework-espidf package.

Also patches the main firmware linker script (memory.ld) to reserve LP SRAM
for the LP core binary. pioarduino's prebuilt memory.ld has lp_ram_seg starting
at 0x50000000 despite CONFIG_ULP_COPROC_RESERVE_MEM=8192 in sdkconfig — this
is a pioarduino bug. Without the patch, .rtc.text lands at 0x50000000 and PMP
marks it RX-only, causing a Store access fault when loading the LP core binary.

Generates C headers for embedding the binary and accessing shared variables.
"""

Import("env")

import os
import subprocess
import sys
from pathlib import Path

# Only run for ESP32-C6 targets
board = env.get("BOARD", "")
if "esp32c6" not in board:
    pass
else:

    PROJ_DIR = Path(env["PROJECT_DIR"])
    ULP_DIR = PROJ_DIR / "ulp"
    BUILD_DIR = PROJ_DIR / ".pio" / "lp_core_build"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    GEN_DIR = BUILD_DIR / "generated"
    GEN_DIR.mkdir(parents=True, exist_ok=True)

    # --- PlatformIO package paths ---

    PACKAGES_DIR = Path.home() / ".platformio" / "packages"
    TOOLCHAIN_DIR = PACKAGES_DIR / "toolchain-riscv32-esp"
    GCC = TOOLCHAIN_DIR / "bin" / "riscv32-esp-elf-gcc"
    OBJCOPY = TOOLCHAIN_DIR / "bin" / "riscv32-esp-elf-objcopy"
    READELF = TOOLCHAIN_DIR / "bin" / "riscv32-esp-elf-readelf"

    if not GCC.exists():
        print(f"ERROR: RISC-V toolchain not found at {GCC}")
        env.Exit(1)

    # pioarduino framework headers
    FW_LIBS = PACKAGES_DIR / "framework-arduinoespressif32-libs" / "esp32c6" / "include"
    if not FW_LIBS.exists():
        print(f"ERROR: pioarduino framework-libs not found at {FW_LIBS}")
        env.Exit(1)

    # ESP-IDF sources (installed by pioarduino's hybrid build dependency)
    IDF_COMPONENTS = PACKAGES_DIR / "framework-espidf" / "components"
    if not IDF_COMPONENTS.exists():
        print(f"ERROR: ESP-IDF framework not found at {IDF_COMPONENTS}")
        print("  Install it with: pio pkg install -g -p espressif32 -t framework-espidf")
        env.Exit(1)

    # --- Path definitions ---

    LP_CORE_DIR = IDF_COMPONENTS / "ulp" / "lp_core" / "lp_core"
    LP_SHARED_DIR = IDF_COMPONENTS / "ulp" / "lp_core" / "shared"

    # Output files
    LP_ELF = BUILD_DIR / "lp_core_main.elf"
    LP_BIN = BUILD_DIR / "lp_core_main.bin"
    LP_SYM = BUILD_DIR / "lp_core_main.sym"
    LP_MAP = BUILD_DIR / "lp_core_main.map"
    LP_LD_PROCESSED = BUILD_DIR / "lp_core_riscv.ld"
    LP_MAPGEN_LD = BUILD_DIR / "lp_core_main.ld"
    LP_HEADER = GEN_DIR / "lp_core_main.h"
    LP_BIN_HEADER = GEN_DIR / "lp_core_main_bin.h"

    SDKCONFIG_H = ULP_DIR / "sdkconfig.h"

    # --- Source files ---

    APP_SOURCES = [
        ULP_DIR / "lp_core_main.c",
    ]

    IDF_SOURCES = [
        LP_CORE_DIR / "start.S",
        LP_CORE_DIR / "vector.S",
        LP_CORE_DIR / "port" / "esp32c6" / "vector_table.S",
        LP_CORE_DIR / "lp_core_startup.c",
        LP_CORE_DIR / "lp_core_utils.c",
        LP_CORE_DIR / "lp_core_i2c.c",
        LP_CORE_DIR / "lp_core_interrupt.c",
        LP_CORE_DIR / "lp_core_panic.c",
        LP_CORE_DIR / "lp_core_print.c",
        LP_CORE_DIR / "lp_core_uart.c",
        LP_CORE_DIR / "lp_core_ubsan.c",
        LP_CORE_DIR / "lp_core_spi.c",
        IDF_COMPONENTS / "hal" / "uart_hal_iram.c",
        IDF_COMPONENTS / "hal" / "uart_hal.c",
        LP_SHARED_DIR / "ulp_lp_core_memory_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_timer_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_uart_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_critical_section_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_adc_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_vad_shared.c",
    ]

    ALL_SOURCES = APP_SOURCES + IDF_SOURCES

    # --- Include directories ---

    INCLUDES = [
        # Project ULP sources (for sdkconfig.h and app headers)
        ULP_DIR,
        # LP core headers from ESP-IDF
        LP_CORE_DIR / "include",
        LP_SHARED_DIR / "include",
        # ld.common (included by lp_core_riscv.ld)
        IDF_COMPONENTS / "esp_system" / "ld",
        # pioarduino framework headers
        FW_LIBS / "riscv" / "include",
        FW_LIBS / "soc" / "esp32c6" / "include",
        FW_LIBS / "soc" / "esp32c6" / "register",
        FW_LIBS / "soc" / "include",
        FW_LIBS / "hal" / "include",
        FW_LIBS / "hal" / "esp32c6" / "include",
        FW_LIBS / "hal" / "platform_port" / "include",
        FW_LIBS / "esp_common" / "include",
        FW_LIBS / "esp_rom" / "include",
        FW_LIBS / "esp_rom" / "esp32c6",
        FW_LIBS / "esp_rom" / "esp32c6" / "include",
        FW_LIBS / "esp_rom" / "esp32c6" / "include" / "esp32c6",
        FW_LIBS / "esp_system" / "port" / "soc",
        FW_LIBS / "esp_hw_support" / "include",
        FW_LIBS / "esp_hw_support" / "include" / "soc",
        FW_LIBS / "esp_hw_support" / "include" / "soc" / "esp32c6",
        FW_LIBS / "esp_hw_support" / "port" / "esp32c6",
        FW_LIBS / "esp_hw_support" / "port" / "esp32c6" / "include",
        # Note: newlib/platform_include intentionally excluded —
        # pioarduino's newlib wrapper conflicts with LP core bare-metal compilation.
        FW_LIBS / "log" / "include",
        FW_LIBS / "esp_timer" / "include",
        FW_LIBS / "esp_driver_uart" / "include",
        FW_LIBS / "heap" / "include",
    ]

    # --- Compiler flags ---

    CFLAGS = [
        "-include", str(SDKCONFIG_H),
        "-Os", "-ggdb",
        "-march=rv32imac_zicsr_zifencei",
        "-mdiv",
        "-fdata-sections", "-ffunction-sections",
        "-fno-builtin",
        "-DIS_ULP_COCPU",
    ]

    ASFLAGS = [
        "-include", str(SDKCONFIG_H),
        "-march=rv32imac_zicsr_zifencei",
        "-x", "assembler-with-cpp",
        "-DIS_ULP_COCPU",
    ]

    LDFLAGS = [
        "-march=rv32imac_zicsr_zifencei",
        "-nostartfiles",
        "-Wl,--gc-sections",
        "-Wl,--no-warn-rwx-segments",
        f"-Wl,-Map={LP_MAP}",
        "--specs=nano.specs",
        "--specs=nosys.specs",
    ]

    # Linker scripts (from ESP-IDF)
    LP_LD_TEMPLATE = IDF_COMPONENTS / "ulp" / "ld" / "lp_core_riscv.ld"
    PERIPHERALS_LD = IDF_COMPONENTS / "soc" / "esp32c6" / "ld" / "esp32c6.peripherals.ld"

    # --- Helper functions ---

    def get_include_flags():
        flags = []
        for inc in INCLUDES:
            flags.extend(["-I", str(inc)])
        return flags

    def needs_rebuild():
        if not LP_BIN_HEADER.exists() or not LP_HEADER.exists():
            return True
        header_text = LP_HEADER.read_text()
        if "placeholder" in header_text or "dummy" in header_text.lower():
            return True
        header_mtime = LP_BIN_HEADER.stat().st_mtime
        for src in ALL_SOURCES:
            if src.exists() and src.stat().st_mtime > header_mtime:
                return True
        if SDKCONFIG_H.exists() and SDKCONFIG_H.stat().st_mtime > header_mtime:
            return True
        return False

    def preprocess_linker_script():
        cmd = [
            str(GCC),
            "-include", str(SDKCONFIG_H),
            "-D__ASSEMBLER__", "-E", "-P", "-xc",
            *get_include_flags(),
            "-o", str(LP_LD_PROCESSED),
            str(LP_LD_TEMPLATE),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: Failed to preprocess linker script:\n{result.stderr}")
            env.Exit(1)

    def compile_source(src):
        obj = BUILD_DIR / (src.stem + ".o")
        is_asm = src.suffix in (".S", ".s")

        cmd = [str(GCC)]
        cmd.extend(ASFLAGS if is_asm else CFLAGS)
        cmd.extend(get_include_flags())
        cmd.extend(["-c", str(src), "-o", str(obj)])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: Failed to compile {src.name}:\n{result.stderr}")
            env.Exit(1)
        return obj

    def link_elf(objects):
        cmd = [str(GCC)]
        cmd.extend(LDFLAGS)
        cmd.extend(["-T", str(LP_LD_PROCESSED)])
        cmd.extend(["-T", str(PERIPHERALS_LD)])
        cmd.extend([str(o) for o in objects])
        cmd.extend(["-o", str(LP_ELF)])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: Failed to link LP core ELF:\n{result.stderr}")
            env.Exit(1)

    def generate_binary():
        cmd = [str(OBJCOPY), "-O", "binary", str(LP_ELF), str(LP_BIN)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: Failed to generate binary:\n{result.stderr}")
            env.Exit(1)

    def generate_symbol_header():
        cmd = [str(READELF), "-sW", str(LP_ELF)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: Failed to read ELF symbols:\n{result.stderr}")
            env.Exit(1)
        LP_SYM.write_text(result.stdout)

        mapgen = IDF_COMPONENTS / "ulp" / "esp32ulp_mapgen.py"
        mapgen_output = BUILD_DIR / "lp_core_main"
        cmd = [
            sys.executable, str(mapgen),
            "-s", str(LP_SYM),
            "-o", str(mapgen_output),
            "--base-addr", "0x0",
            "-p", "ulp_",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: Failed to run mapgen:\n{result.stderr}")
            env.Exit(1)

        import shutil
        shutil.copy2(str(mapgen_output) + ".h", str(LP_HEADER))

    def generate_binary_header():
        bin_data = LP_BIN.read_bytes()
        lines = [
            "// Auto-generated LP core binary — do not edit.",
            "// Regenerated by scripts/build_lp_core.py",
            "#pragma once",
            "#include <stdint.h>",
            "",
            "const uint8_t lp_core_main_bin[] = {",
        ]
        for i in range(0, len(bin_data), 16):
            chunk = bin_data[i:i+16]
            hex_str = ", ".join(f"0x{b:02x}" for b in chunk)
            lines.append(f"    {hex_str},")
        lines.append("};")
        lines.append(f"const size_t lp_core_main_bin_length = {len(bin_data)};")
        lines.append("")
        LP_BIN_HEADER.write_text("\n".join(lines))

    # --- Main build logic (runs at script load time, before compilation) ---

    if not needs_rebuild():
        print("LP core binary is up to date")
    else:
        print("Building LP core binary...")

        print("  Preprocessing linker script...")
        preprocess_linker_script()

        objects = []
        for src in ALL_SOURCES:
            if not src.exists():
                print(f"  WARNING: Source file not found: {src}")
                continue
            print(f"  Compiling {src.name}...")
            obj = compile_source(src)
            objects.append(obj)

        print("  Linking LP core ELF...")
        link_elf(objects)

        print("  Generating binary...")
        generate_binary()
        bin_size = LP_BIN.stat().st_size
        print(f"  LP core binary size: {bin_size} bytes")

        print("  Generating symbol header...")
        generate_symbol_header()

        print("  Generating binary header...")
        generate_binary_header()

        print("LP core binary built successfully")

    # --- Patch main firmware memory.ld to reserve LP SRAM ---
    #
    # pioarduino bug: prebuilt memory.ld has lp_ram_seg starting at 0x50000000
    # despite CONFIG_ULP_COPROC_RESERVE_MEM=8192. We patch it to start at
    # 0x50000000 + 8192 so PMP marks the first 8KB as RW (for LP core binary)
    # instead of RX (for .rtc.text).

    import re

    LP_RESERVE = 8192
    FW_LD_DIR = PACKAGES_DIR / "framework-arduinoespressif32-libs" / "esp32c6" / "ld"
    PATCHED_LD_DIR = BUILD_DIR / "ld"
    PATCHED_LD_DIR.mkdir(parents=True, exist_ok=True)

    memory_ld_src = FW_LD_DIR / "memory.ld"
    memory_ld_dst = PATCHED_LD_DIR / "memory.ld"

    if memory_ld_src.exists():
        text = memory_ld_src.read_text()
        # Patch: lp_ram_seg(RW) : org = 0x50000000, len = ...
        # →      lp_ram_seg(RW) : org = 0x50000000 + 8192, len = ... - 8192
        patched = re.sub(
            r'(lp_ram_seg\(RW\)\s*:\s*org\s*=\s*0x50000000)\s*,\s*len\s*=\s*([^\n]+)',
            rf'\1 + {LP_RESERVE}, len = \2 - {LP_RESERVE}',
            text,
        )
        if patched != text:
            memory_ld_dst.write_text(patched)
            # Prepend our ld/ dir so it's found before the framework's
            env.Prepend(LIBPATH=[str(PATCHED_LD_DIR)])
            print(f"Patched memory.ld: lp_ram_seg starts at 0x50000000 + {LP_RESERVE}")
        else:
            print("WARNING: Could not patch memory.ld — LP SRAM may not be writable")

    # Add generated headers to include path and mapgen linker script to link
    env.Append(CPPPATH=[str(GEN_DIR)])
    env.Append(LINKFLAGS=["-T", str(LP_MAPGEN_LD)])
