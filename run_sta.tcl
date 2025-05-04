
read_liberty my.lib
read_verilog temp.v
link_design gcd
read_sdc design.sdc
read_spef design.spef
source derate.tcl
report_checks -path_delay max -sort_by_slack > timing.txt
report_wns > wns.txt
report_tns > tns.txt
exit
