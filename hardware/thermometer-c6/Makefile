SCH  := thermometer-c6.kicad_sch
PCB  := thermometer-c6.kicad_pcb
OUT  := out

FAB      := $(OUT)/fab
GITHASH   = $(shell git rev-parse --short HEAD)
TODAY     = $(shell date +%Y-%m-%d)
FAB_STAMP = $(GITHASH) $(TODAY)
# Revision letter comes from circuit.py (the single source of truth) so this
# echo can never disagree with what is actually on the silk.
REV       = $(shell python3 -c 'import sys; sys.path.insert(0,"generator"); import circuit; print(circuit.REV)')
FABPCB   := $(FAB)/board/$(PCB)

.PHONY: all gen erc netlist check invariants pdf svg fab clean pcb route route-pf freeroute drc pcb-img hand

all: check pdf

gen:
	python3 generator/generate.py

$(OUT):
	mkdir -p $(OUT)

erc: gen | $(OUT)
	kicad-cli sch erc --severity-all --exit-code-violations --format json -o $(OUT)/erc.json $(SCH) \
		|| (python3 -c "import json;d=json.load(open('$(OUT)/erc.json'));[print(v['severity'],v['type'],'-',v['description'],[i.get('description') for i in v.get('items',[])]) for s in d.get('sheets',[]) for v in s.get('violations',[])]"; exit 1)
	@echo "ERC: clean"

netlist: gen | $(OUT)
	kicad-cli sch export netlist --format kicadsexpr -o $(OUT)/netlist.net $(SCH)
	python3 verify/check_netlist.py $(OUT)/netlist.net

invariants: netlist
	python3 verify/invariants.py $(OUT)/netlist.net

check: erc netlist invariants
	python3 verify/check_footprints.py
	@echo "ALL CHECKS PASSED"

pcb: netlist
	python3 generator/pcb.py

# regenerate generator/pcb_routes.py with the A* autorouter (checked in;
# slow, run explicitly), then re-render the board with the new routes.
# The re-render must happen even when the router leaves terminals unrouted,
# else the board keeps the previous pass's copper over the new placement.
route: pcb
	python3 generator/route.py; rc=$$?; python3 generator/pcb.py; exit $$rc

# PathFinder (negotiated-congestion) experiment router. Same output contract as
# `route`: regenerate generator/pcb_routes.py, then re-render the board. Stage 1
# keeps all authored copper immovable, so the render is pl.TRACKS + pcb_routes
# exactly like `route` -- no separate render path needed.
route-pf: pcb
	python3 generator/pathfind.py; rc=$$?; python3 generator/pcb.py; exit $$rc

# Freerouting DSN round-trip experiment (opens the Freerouting GUI; needs
# java + a display). Writes out/freerouting/routed-a.kicad_pcb for review --
# nothing is harvested automatically. Findings: PATHFINDER-NOTES.md (negative:
# same 12 stragglers as the greedy router; 2.2.4 crashes, use 1.9.0).
FRJAR := $(OUT)/freerouting/freerouting-1.9.0.jar
$(FRJAR):
	mkdir -p $(OUT)/freerouting
	curl -sL -o $@ https://github.com/freerouting/freerouting/releases/download/v1.9.0/freerouting-1.9.0.jar
freeroute: pcb $(FRJAR)
	python3 generator/freeroute.py --jar $(FRJAR)

drc: pcb | $(OUT)
	kicad-cli pcb drc --severity-all --exit-code-violations --schematic-parity --refill-zones \
		--format json -o $(OUT)/drc.json $(PCB) \
		|| (python3 -c "import json;d=json.load(open('$(OUT)/drc.json'));\
[print(v['severity'],v['type'],'-',v['description'],[i.get('description') for i in v.get('items',[])]) \
for k in ('violations','unconnected_items','schematic_parity') for v in d.get(k,[])]" | head -80; exit 1)
	@echo "DRC: clean"

# Fab export (rev A): render a git-hash+date-stamped standalone board into
# out/fab/, strict-DRC-gate the stamped board, and emit JLCPCB gerbers + drill +
# placement. Refuses a dirty tree so the "rev A <hash> <date>" silk stamp names
# the exact committed source (FAB_FORCE=1 warns instead of failing). The fab DRC
# is the full-severity run on the *stamped* board (what actually ships) gated by
# `drc_summary --gate-fab` (REAL=0 AND DEFERRED=0; every remaining violation must
# be explicitly waived by a scoped rule -- currently NONE, since the J3
# edge-launch copper_edge_clearance waiver was deleted with the 2026-07-20 datum
# respin that removed its cause). `git checkout -- $(PCB)` is a defensive restore of the
# committed board against any stray non-byte-stable zone-fill noise before the
# tree-clean guard, so only real source changes trip it.
fab: check
	@git checkout -- $(PCB)
	@git diff --quiet && git diff --cached --quiet || \
	  { [ "$(FAB_FORCE)" = "1" ] && echo "fab: WARNING dirty tree, stamp $(GITHASH) is a lie" || \
	    { echo "fab: dirty git tree -- commit first (FAB_FORCE=1 to override)"; exit 1; }; }
	python3 verify/check_pcb.py
	rm -rf $(FAB) generator/__pycache__
	mkdir -p $(FAB)/board $(FAB)/gerbers
	PYTHONDONTWRITEBYTECODE=1 FAB_STAMP="$(FAB_STAMP)" PCB_OUT_DIR=$(FAB)/board \
	  python3 generator/pcb.py
	cp $(SCH) $(FAB)/board/
	kicad-cli pcb drc --severity-all --schematic-parity --refill-zones \
	  --format json -o $(FAB)/drc.json $(FABPCB)
	python3 verify/drc_summary.py --gate-fab $(FAB)/drc.json
	python3 verify/check_pcb.py $(FABPCB)
	kicad-cli pcb export gerbers \
	  --layers Edge.Cuts,F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,F.Paste,B.Paste \
	  --subtract-soldermask --check-zones -o $(FAB)/gerbers/ $(FABPCB)
	kicad-cli pcb export drill --format excellon --excellon-units mm \
	  --excellon-zeros-format decimal --excellon-oval-format alternate \
	  --drill-origin absolute --generate-map --map-format gerberx2 \
	  -o $(FAB)/gerbers/ $(FABPCB)
	kicad-cli pcb export pos --format csv --units mm --side front \
	  -o $(FAB)/pos-raw.csv $(FABPCB)
	PYTHONDONTWRITEBYTECODE=1 python3 generator/fab_cpl.py $(FABPCB) \
	  -o $(FAB)/thermometer-c6-cpl.csv --checklist $(FAB)/rotation-checklist.md
	cp bom/thermometer-c6-bom.csv $(FAB)/
	cd $(FAB)/gerbers && python3 -m zipfile -c ../thermometer-c6-gerbers-$(GITHASH)-$(TODAY).zip *
	PYTHONDONTWRITEBYTECODE=1 python3 verify/check_fab.py $(FAB) --stamp "$(FAB_STAMP)"
	@echo "FAB EXPORT OK: $(FAB) (stamp: rev $(REV) $(FAB_STAMP))"

# GUI hand-routing copy (HAND-ROUTING.md step 1). Run `make pcb` first.
#
# The .kicad_dru MUST come along: without it the GUI -- and any kicad-cli drc
# run from this directory -- silently loses every scoped waiver rule and
# reports violations the real board does not have (68 vs 7, observed).
#
# local.3dmodels is SYMLINKED, not copied: the board stores its model paths as
# ${KIPRJMOD}/local.3dmodels/<part>.step, and KIPRJMOD resolves to whichever
# directory holds the .kicad_pro -- so in out/hand/ the local STEP models go
# unresolved and the 3D viewer falls back to bare pads. A symlink fixes that
# without duplicating the files or baking an absolute path into the board.
#
# Refuses if the existing copy is newer than the generated board, since that
# means un-harvested GUI edits. FORCE=1 discards them.
hand: | $(OUT)
	@if [ -e $(OUT)/hand/$(PCB) ] && [ $(OUT)/hand/$(PCB) -nt $(PCB) ] && [ -z "$(FORCE)" ]; then \
	  echo "REFUSING: $(OUT)/hand/$(PCB) is newer than $(PCB)."; \
	  echo "  It may hold un-harvested GUI edits, which this would overwrite."; \
	  echo "  Harvest first (HAND-ROUTING.md step 3), or re-run with FORCE=1."; \
	  exit 1; \
	fi
	mkdir -p $(OUT)/hand
	cp $(PCB) thermometer-c6.kicad_pro thermometer-c6.kicad_dru $(OUT)/hand/
	ln -sfn ../../local.3dmodels $(OUT)/hand/local.3dmodels
	@echo "HAND COPY READY: $(OUT)/hand/$(PCB) (DRU + local 3D models linked)"

pcb-img: pcb | $(OUT)
	kicad-cli pcb export svg --mode-multi --layers F.Cu,B.Cu,Edge.Cuts,F.SilkS,B.SilkS,F.Fab -o $(OUT)/pcb-svg $(PCB)
	kicad-cli pcb render --side top -o $(OUT)/pcb-top.png $(PCB)
	kicad-cli pcb render --side bottom -o $(OUT)/pcb-bottom.png $(PCB)

pdf: gen | $(OUT)
	kicad-cli sch export pdf -o $(OUT)/$(basename $(SCH)).pdf $(SCH)

svg: gen | $(OUT)
	kicad-cli sch export svg -o $(OUT)/svg $(SCH)

clean:
	rm -rf $(OUT)
