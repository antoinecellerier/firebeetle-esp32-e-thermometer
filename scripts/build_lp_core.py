"""
PlatformIO pre-build script for compiling the ESP32-C6 LP core binary.

Uses the RISC-V toolchain from PlatformIO packages and ESP-IDF LP core
sources (auto-downloaded on first build) to compile the LP core program.
Headers come from pioarduino's framework-arduinoespressif32-libs package.

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
    IDF_DIR = ULP_DIR / "idf"
    BUILD_DIR = PROJ_DIR / ".pio" / "lp_core_build"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # Find toolchain from PlatformIO packages
    TOOLCHAIN_DIR = Path.home() / ".platformio" / "packages" / "toolchain-riscv32-esp"
    GCC = TOOLCHAIN_DIR / "bin" / "riscv32-esp-elf-gcc"
    OBJCOPY = TOOLCHAIN_DIR / "bin" / "riscv32-esp-elf-objcopy"
    READELF = TOOLCHAIN_DIR / "bin" / "riscv32-esp-elf-readelf"

    if not GCC.exists():
        print(f"ERROR: RISC-V toolchain not found at {GCC}")
        env.Exit(1)

    # pioarduino framework headers (already installed by PlatformIO)
    FW_LIBS = Path.home() / ".platformio" / "packages" / "framework-arduinoespressif32-libs" / "esp32c6" / "include"
    if not FW_LIBS.exists():
        print(f"ERROR: pioarduino framework-libs not found at {FW_LIBS}")
        env.Exit(1)

    # --- ESP-IDF source download ---
    # Auto-detect ESP-IDF version from pioarduino's framework headers.
    def detect_idf_version():
        ver_header = FW_LIBS / "esp_common" / "include" / "esp_idf_version.h"
        if not ver_header.exists():
            print(f"ERROR: Cannot detect ESP-IDF version: {ver_header} not found")
            env.Exit(1)
        import re
        text = ver_header.read_text()
        major = re.search(r"ESP_IDF_VERSION_MAJOR\s+(\d+)", text)
        minor = re.search(r"ESP_IDF_VERSION_MINOR\s+(\d+)", text)
        patch = re.search(r"ESP_IDF_VERSION_PATCH\s+(\d+)", text)
        if not (major and minor and patch):
            print("ERROR: Cannot parse ESP-IDF version from header")
            env.Exit(1)
        return f"v{major.group(1)}.{minor.group(1)}.{patch.group(1)}"

    IDF_TAG = detect_idf_version()
    IDF_RAW_BASE = f"https://raw.githubusercontent.com/espressif/esp-idf/{IDF_TAG}"

    # Files to download from ESP-IDF (paths relative to components/)
    IDF_FILES = [
        # LP core framework sources
        "ulp/lp_core/lp_core/start.S",
        "ulp/lp_core/lp_core/vector.S",
        "ulp/lp_core/lp_core/port/esp32c6/vector_table.S",
        "ulp/lp_core/lp_core/lp_core_startup.c",
        "ulp/lp_core/lp_core/lp_core_utils.c",
        "ulp/lp_core/lp_core/lp_core_i2c.c",
        "ulp/lp_core/lp_core/lp_core_interrupt.c",
        "ulp/lp_core/lp_core/lp_core_panic.c",
        "ulp/lp_core/lp_core/lp_core_print.c",
        "ulp/lp_core/lp_core/lp_core_uart.c",
        "ulp/lp_core/lp_core/lp_core_ubsan.c",
        "ulp/lp_core/lp_core/lp_core_spi.c",
        # LP core headers (not in pioarduino since ULP is disabled)
        "ulp/lp_core/lp_core/include/ulp_lp_core_gpio.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_i2c.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_interrupts.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_print.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_spi.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_touch.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_uart.h",
        "ulp/lp_core/lp_core/include/ulp_lp_core_utils.h",
        # Shared memory sources and headers
        "ulp/lp_core/shared/ulp_lp_core_memory_shared.c",
        "ulp/lp_core/shared/ulp_lp_core_lp_timer_shared.c",
        "ulp/lp_core/shared/ulp_lp_core_lp_uart_shared.c",
        "ulp/lp_core/shared/ulp_lp_core_critical_section_shared.c",
        "ulp/lp_core/shared/ulp_lp_core_lp_adc_shared.c",
        "ulp/lp_core/shared/ulp_lp_core_lp_vad_shared.c",
        "ulp/lp_core/shared/include/ulp_lp_core_critical_section_shared.h",
        "ulp/lp_core/shared/include/ulp_lp_core_lp_adc_shared.h",
        "ulp/lp_core/shared/include/ulp_lp_core_lp_timer_shared.h",
        "ulp/lp_core/shared/include/ulp_lp_core_lp_uart_shared.h",
        "ulp/lp_core/shared/include/ulp_lp_core_lp_vad_shared.h",
        "ulp/lp_core/shared/include/ulp_lp_core_memory_shared.h",
        # UART HAL (dependency of LP core UART/print)
        "hal/uart_hal_iram.c",
        "hal/uart_hal.c",
        # Linker scripts
        "ulp/ld/lp_core_riscv.ld",
        "soc/esp32c6/ld/esp32c6.peripherals.ld",
        # ld.common (included by lp_core_riscv.ld)
        "esp_system/ld/ld.common",
        # Symbol generator
        "ulp/esp32ulp_mapgen.py",
    ]

    def download_idf_sources():
        """Download required ESP-IDF files from GitHub."""
        import urllib.request
        import urllib.error

        marker = IDF_DIR / ".idf_tag"
        if marker.exists() and marker.read_text().strip() == IDF_TAG:
            return  # Already downloaded for this version

        print(f"Downloading ESP-IDF {IDF_TAG} LP core sources...")
        for rel_path in IDF_FILES:
            url = f"{IDF_RAW_BASE}/components/{rel_path}"
            dest = IDF_DIR / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                urllib.request.urlretrieve(url, str(dest))
            except urllib.error.HTTPError as e:
                print(f"  ERROR: Failed to download {rel_path}: {e}")
                env.Exit(1)

        marker.write_text(IDF_TAG + "\n")
        print(f"  Downloaded {len(IDF_FILES)} files")

    download_idf_sources()

    # --- Path definitions ---

    LP_CORE_DIR = IDF_DIR / "ulp" / "lp_core" / "lp_core"
    LP_SHARED_DIR = IDF_DIR / "ulp" / "lp_core" / "shared"

    # Output files
    LP_ELF = BUILD_DIR / "lp_core_main.elf"
    LP_BIN = BUILD_DIR / "lp_core_main.bin"
    LP_SYM = BUILD_DIR / "lp_core_main.sym"
    LP_MAP = BUILD_DIR / "lp_core_main.map"
    LP_LD_PROCESSED = BUILD_DIR / "lp_core_riscv.ld"
    LP_MAPGEN_LD = BUILD_DIR / "lp_core_main.ld"
    GEN_DIR = PROJ_DIR / "include" / "generated"
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    LP_HEADER = GEN_DIR / "lp_core_main.h"
    LP_BIN_HEADER = GEN_DIR / "lp_core_main_bin.h"

    SDKCONFIG_H = ULP_DIR / "sdkconfig.h"

    # --- Source files ---

    APP_SOURCES = [
        ULP_DIR / "lp_core_bmp390l.c",
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
        IDF_DIR / "hal" / "uart_hal_iram.c",
        IDF_DIR / "hal" / "uart_hal.c",
        LP_SHARED_DIR / "ulp_lp_core_memory_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_timer_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_uart_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_critical_section_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_adc_shared.c",
        LP_SHARED_DIR / "ulp_lp_core_lp_vad_shared.c",
    ]

    ALL_SOURCES = APP_SOURCES + IDF_SOURCES

    # --- Include directories ---
    # LP core-specific headers (downloaded, not in pioarduino)
    INCLUDES = [
        ULP_DIR,
        LP_CORE_DIR / "include",
        LP_SHARED_DIR / "include",
    ]

    # ld.common is in the downloaded IDF sources
    INCLUDES.append(IDF_DIR / "esp_system" / "ld")

    # All other headers come from pioarduino's framework-libs
    FW_INCLUDES = [
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
        # Note: newlib/platform_include is intentionally NOT included here.
        # pioarduino's newlib wrapper conflicts with LP core bare-metal compilation.
        FW_LIBS / "log" / "include",
        FW_LIBS / "esp_timer" / "include",
        FW_LIBS / "esp_driver_uart" / "include",
        FW_LIBS / "heap" / "include",
    ]
    INCLUDES.extend(FW_INCLUDES)

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

    # Linker scripts
    LP_LD_TEMPLATE = IDF_DIR / "ulp" / "ld" / "lp_core_riscv.ld"
    PERIPHERALS_LD = IDF_DIR / "soc" / "esp32c6" / "ld" / "esp32c6.peripherals.ld"

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

        mapgen = IDF_DIR / "ulp" / "esp32ulp_mapgen.py"
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
            "// Auto-generated LP core binary for ESP32-C6 BMP390L reader.",
            "// Do not edit — regenerated by scripts/build_lp_core.py",
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

    # Add the mapgen linker script to the main firmware link
    env.Append(LINKFLAGS=["-T", str(LP_MAPGEN_LD)])
