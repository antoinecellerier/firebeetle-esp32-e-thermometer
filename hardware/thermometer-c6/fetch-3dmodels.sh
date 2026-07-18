#!/usr/bin/env bash
# Fetch the 3D STEP models for the footprints kicad-packages3d can't render.
#
# The six local footprints (local.pretty/*) ship no (model), and the two stock
# KiCad footprints J1 (JST-PH) and J3 (USB-C) point at STEP files that are not
# in the installed 3D library. All seven models are pulled from EasyEDA/LCSC via
# easyeda2kicad, keyed by the same LCSC part numbers as the BOM, and dropped in
# local.3dmodels/ under the names pcb_layout.MODELS_3D expects. That directory is
# gitignored (like datasheets/) — rerun this any time to repopulate it.
#
# Needs: python3 (venv). easyeda2kicad is bootstrapped into a throwaway venv if
# it is not already on PATH. Run from anywhere: ./fetch-3dmodels.sh
set -euo pipefail
cd "$(dirname "$0")"
DST="local.3dmodels"
mkdir -p "$DST"

# LCSC id -> target filename (must match generator/pcb_layout.py MODELS_3D)
LCSC_IDS=(C5736265 C295747 C165948 C2856831 C318884 C5362283 C18184976)
declare -A NAME=(
  [C5736265]="ESP32-C6-MINI-1.step"                     # U1  ESP32-C6-MINI-1-N4
  [C295747]="JST_PH_S2B-PH-SM4-TB_Horizontal.step"      # J1  battery JST-PH
  [C165948]="USB_C_Receptacle_HRO_TYPE-C-31-M-12.step"  # J3  USB-C
  [C2856831]="XUNPU_FPC-05FB-24PH20.step"               # J4  EPD FPC-24 0.5mm
  [C318884]="SW_TS-1187A.step"                          # SW1/SW2 tactile
  [C5362283]="Bosch_LGA-10_2x2mm_BMP581.step"           # U5  BMP581
  [C18184976]="Bosch_LGA-9_3.25x3.25mm_BMP585.step"     # U6  BMP585 (fit-one)
)

E2K="$(command -v easyeda2kicad || true)"
if [ -z "$E2K" ]; then
  echo "easyeda2kicad not found; bootstrapping a throwaway venv..."
  VENV="$(mktemp -d)/venv"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q easyeda2kicad
  E2K="$VENV/bin/easyeda2kicad"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for code in "${LCSC_IDS[@]}"; do
  mkdir -p "$TMP/$code"        # easyeda2kicad requires the output folder to exist
  "$E2K" --lcsc_id "$code" --3d --output "$TMP/$code/lib" --overwrite >/dev/null
  src="$(ls "$TMP/$code"/lib.3dshapes/*.step | head -1)"
  cp "$src" "$DST/${NAME[$code]}"
  echo "  ${NAME[$code]}  <- $code"
done
echo "Done: $DST/ (${#LCSC_IDS[@]} models)"
