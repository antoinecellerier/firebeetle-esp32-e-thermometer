SCH  := thermometer-c6.kicad_sch
OUT  := out

.PHONY: all gen erc netlist check invariants pdf svg bom clean

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

pdf: gen | $(OUT)
	kicad-cli sch export pdf -o $(OUT)/$(basename $(SCH)).pdf $(SCH)

svg: gen | $(OUT)
	kicad-cli sch export svg -o $(OUT)/svg $(SCH)

clean:
	rm -rf $(OUT)
