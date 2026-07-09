SCH  := thermometer-c6.kicad_sch
PCB  := thermometer-c6.kicad_pcb
OUT  := out

.PHONY: all gen erc netlist check invariants pdf svg bom clean pcb route drc pcb-img

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

drc: pcb | $(OUT)
	kicad-cli pcb drc --severity-all --exit-code-violations --schematic-parity --refill-zones \
		--format json -o $(OUT)/drc.json $(PCB) \
		|| (python3 -c "import json;d=json.load(open('$(OUT)/drc.json'));\
[print(v['severity'],v['type'],'-',v['description'],[i.get('description') for i in v.get('items',[])]) \
for k in ('violations','unconnected_items','schematic_parity') for v in d.get(k,[])]" | head -80; exit 1)
	@echo "DRC: clean"

pcb-img: pcb | $(OUT)
	kicad-cli pcb export svg --mode-multi --layers F.Cu,B.Cu,Edge.Cuts,F.SilkS,F.Fab -o $(OUT)/pcb-svg $(PCB)
	kicad-cli pcb render --side top -o $(OUT)/pcb-top.png $(PCB)
	kicad-cli pcb render --side bottom -o $(OUT)/pcb-bottom.png $(PCB)

pdf: gen | $(OUT)
	kicad-cli sch export pdf -o $(OUT)/$(basename $(SCH)).pdf $(SCH)

svg: gen | $(OUT)
	kicad-cli sch export svg -o $(OUT)/svg $(SCH)

clean:
	rm -rf $(OUT)
