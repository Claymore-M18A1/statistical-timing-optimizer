# Auto-generated run_sta.tcl
read_liberty my.lib
read_verilog sa_candidate.v
link_design gcd
read_sdc design.sdc
read_spef design.spef
source sa_derate.tcl
report_checks -path_delay max -sort_by_slack -format full_clock_expanded > timing.txt
report_wns > wns.txt
report_tns > tns.txt
exit
