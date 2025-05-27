import numpy as np
import subprocess
import time
import re
import os

# --- Utility Functions for STA ---

def generate_derate(path="derate.tcl", mu=1.0, sigma_delay=0.02, sigma_check=0.02):
    """Generates a Tcl file with random timing derates."""
    # Ensure non-negative derates, although STA tools might handle small negatives
    delay_derate = max(0.1, np.random.normal(mu, sigma_delay)) # Avoid zero or negative
    check_derate = max(0.1, np.random.normal(mu, sigma_check)) # Avoid zero or negative
    try:
        with open(path, "w") as f:
            f.write(f"# Generated Derates: mu={mu}, sigma_delay={sigma_delay}, sigma_check={sigma_check}\n")
            f.write(f"set_timing_derate -late -cell_delay {delay_derate:.4f}\n")
            f.write(f"set_timing_derate -late -cell_check {check_derate:.4f}\n")
            # Add early derates if needed for setup checks (often 1.0 or slightly less)
            # f.write(f"set_timing_derate -early -cell_delay {1.0:.4f}\n")
            # f.write(f"set_timing_derate -early -cell_check {1.0:.4f}\n")
    except IOError as e:
        print(f"[ERROR] Failed to write derate file {path}: {e}")

def generate_run_tcl(tcl_path="run_sta.tcl", verilog_path="design.v", design_name="gcd", sdc_path="design.sdc", lib_path="my.lib", spef_path="design.spef", derate_tcl="derate.tcl", timing_report="timing.txt", wns_report="wns.txt", tns_report="tns.txt"):
    """Generates the run_sta.tcl script."""
    try:
        with open(tcl_path, "w") as f:
            f.write("# Auto-generated run_sta.tcl\n")
            f.write(f"read_liberty {lib_path}\n")
            f.write(f"read_verilog {verilog_path}\n")
            f.write(f"link_design {design_name}\n")
            f.write(f"read_sdc {sdc_path}\n")
            if spef_path and os.path.exists(spef_path):
                f.write(f"read_spef {spef_path}\n")
            else:
                print(f"[Warning] SPEF file '{spef_path}' not found or specified, skipping read_spef.")
            if derate_tcl and os.path.exists(derate_tcl):
                f.write(f"source {derate_tcl}\n")
            else:
                print(f"[Warning] Derate file '{derate_tcl}' not found or specified, skipping derate source.")

            # Generate more detailed timing reports
            f.write(f"report_checks -path_delay max -sort_by_slack -format full_clock_expanded > {timing_report}\n")
            f.write(f"report_wns > {wns_report}\n")
            f.write(f"report_tns > {tns_report}\n")
            f.write("exit\n")
        return True
    except IOError as e:
        print(f"[ERROR] Failed to write Tcl script {tcl_path}: {e}")
        return False

def parse_timing_report(report_path):
    """Parse the detailed timing report to extract gate-specific timing information."""
    gate_timing = {}
    current_gate = None
    current_path = None
    
    try:
        with open(report_path, 'r') as f:
            for line in f:
                # Look for path start
                if 'Startpoint' in line:
                    current_path = line.split(':')[1].strip()
                
                # Look for gate instances
                elif 'Instance' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        current_gate = parts[1]
                        if current_gate not in gate_timing:
                            gate_timing[current_gate] = {
                                'delay': 0.0,
                                'slew': 0.0,
                                'slack': 0.0,
                                'path_type': None,
                                'path': current_path
                            }
                
                # Extract timing information
                elif current_gate:
                    if 'delay' in line.lower():
                        try:
                            delay = float(line.split()[-2])
                            gate_timing[current_gate]['delay'] = max(gate_timing[current_gate]['delay'], delay)
                        except (ValueError, IndexError):
                            pass
                    elif 'slew' in line.lower():
                        try:
                            slew = float(line.split()[-2])
                            gate_timing[current_gate]['slew'] = max(gate_timing[current_gate]['slew'], slew)
                        except (ValueError, IndexError):
                            pass
                    elif 'slack' in line.lower():
                        try:
                            slack = float(line.split()[-2])
                            # Keep the worst (most negative) slack
                            if slack < gate_timing[current_gate]['slack']:
                                gate_timing[current_gate]['slack'] = slack
                        except (ValueError, IndexError):
                            pass
                    elif 'path type' in line.lower():
                        path_type = line.split()[-1]
                        if gate_timing[current_gate]['path_type'] is None:
                            gate_timing[current_gate]['path_type'] = path_type
        
        # Print debug information
        print("\n    --- Timing Report Summary ---")
        for gate, timing in gate_timing.items():
            print(f"    Gate: {gate}")
            print(f"      Path: {timing['path']}")
            print(f"      Delay: {timing['delay']:.4f} ns")
            print(f"      Slew: {timing['slew']:.4f} ns")
            print(f"      Slack: {timing['slack']:.4f} ns")
            print(f"      Path Type: {timing['path_type']}")
        print("    --- End Timing Report Summary ---\n")
        
        return gate_timing
    except Exception as e:
        print(f"[Warning] Error parsing timing report: {e}")
        return {}

# Keep WNS/TNS parsing separate as they have dedicated reports
def parse_wns(path="wns.txt"):
    try:
        with open(path) as f:
            content = f.read()
            # More robust regex: handles different whitespace, optional sign
            match = re.search(r'(?:wns|worst slack)\s+\w*\s*([+-]?\d+\.?\d*)', content, re.IGNORECASE)
            if match:
                return float(match.group(1))
            else:
                print(f"[Warning] Could not find WNS value in {path}")
    except FileNotFoundError:
         print(f"[Warning] WNS report file not found: {path}")
    except ValueError:
        print(f"[Warning] Could not parse WNS float from {path}")
    except Exception as e:
        print(f"[Warning] Failed to parse WNS from {path}: {e}")
    return None

def parse_tns(path="tns.txt"):
    try:
        with open(path) as f:
            content = f.read()
            # More robust regex
            match = re.search(r'(?:tns|total negative slack)\s+\w*\s*([+-]?\d+\.?\d*)', content, re.IGNORECASE)
            if match:
                return float(match.group(1))
            else:
                 print(f"[Warning] Could not find TNS value in {path}")
    except FileNotFoundError:
         print(f"[Warning] TNS report file not found: {path}")
    except ValueError:
        print(f"[Warning] Could not parse TNS float from {path}")
    except Exception as e:
        print(f"[Warning] Failed to parse TNS from {path}: {e}")
    return None


def run_sta(verilog_file="design.v", design_name="gcd", sdc_path="design.sdc", lib_path="my.lib", spef_path="design.spef", derate_tcl="derate.tcl"):
    """Run OpenSTA and return WNS and TNS values."""
    # Generate TCL script
    tcl_script = "run_sta.tcl"
    timing_report = "timing.txt"
    wns_report = "wns.txt"
    tns_report = "tns.txt"
    
    if not generate_run_tcl(tcl_script, verilog_file, design_name, sdc_path, lib_path, spef_path, derate_tcl, 
                          timing_report, wns_report, tns_report):
        print("[ERROR] Failed to generate TCL script")
        return None, None

    # Print the TCL script for debugging
    print("\n--- Generated TCL Script ---")
    with open(tcl_script, 'r') as f:
        print(f.read())
    print("--- End TCL Script ---\n")

    # Run OpenSTA directly
    try:
        # Use OpenSTA directly since we're already in a container
        opensta_cmd = "/usr/local/bin/opensta"
        
        print(f"[INFO] Running OpenSTA: {opensta_cmd} {tcl_script}")
        
        result = subprocess.run([opensta_cmd, tcl_script], 
                              capture_output=True, 
                              text=True,
                              check=True)
        
        print("\n--- OpenSTA Output ---")
        print(result.stdout)
        if result.stderr:
            print("\n--- OpenSTA Errors ---")
            print(result.stderr)
        print("--- End OpenSTA Output ---\n")
        
        # Parse timing reports
        wns = parse_wns(wns_report)
        tns = parse_tns(tns_report)
        gate_timing = parse_timing_report(timing_report)
        
        if wns is None or tns is None:
            print("[WARNING] Failed to parse timing reports")
            return None, None
            
        print(f"[INFO] WNS: {wns:.4f} ns, TNS: {tns:.4f} ns")
        
        # Print detailed timing information
        if gate_timing:
            print("\n--- Detailed Timing Information ---")
            for gate, timing in gate_timing.items():
                print(f"Gate: {gate}")
                print(f"  Path: {timing['path']}")
                print(f"  Delay: {timing['delay']:.4f} ns")
                print(f"  Slew: {timing['slew']:.4f} ns")
                print(f"  Slack: {timing['slack']:.4f} ns")
                print(f"  Path Type: {timing['path_type']}")
            print("--- End Detailed Timing Information ---\n")
        
        return wns, tns
        
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] OpenSTA failed with return code {e.returncode}")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        return None, None
    except Exception as e:
        print(f"[ERROR] Unexpected error running OpenSTA: {e}")
        return None, None
    finally:
        # Only clean up the TCL script, keep the report files
        if os.path.exists(tcl_script):
            try:
                os.remove(tcl_script)
            except OSError:
                pass

# --- Standalone Monte Carlo Analysis ---
def monte_carlo_main(verilog_file="design.v", num_runs=10, design_name="gcd", sdc_path="design.sdc", lib_path="my.lib", spef_path="design.spef"):
    """Runs multiple STA iterations with varying derates."""
    print(f"\nStarting Monte Carlo STA Analysis for {verilog_file}...")
    yield_count = 0
    wns_list = []
    tns_list = []
    derate_file = "derate_mc.tcl"

    required_files = [verilog_file, sdc_path, lib_path]
    if spef_path: required_files.append(spef_path)
    for f in required_files:
         if not os.path.exists(f):
              print(f"[ERROR] Required file not found: {f}")
              return

    for i in range(num_runs):
        print(f"\n--- MC Run {i+1}/{num_runs} ---")
        # Generate new derate factors for this run
        generate_derate(path=derate_file)

        # Run STA with the current derate file
        wns, tns = run_sta(verilog_file=verilog_file, design_name=design_name, sdc_path=sdc_path, lib_path=lib_path, spef_path=spef_path, derate_tcl=derate_file)

        if wns is not None and tns is not None:
            wns_list.append(wns)
            tns_list.append(tns)
            # Consider yield based on WNS >= 0 and TNS >= 0 (or TNS == 0 if WNS >=0)
            passed = (wns >= 0 and tns >= 0) # Stricter check: TNS must be non-negative
            # Alternative: passed = (wns >= 0) # Yield based only on WNS
            if passed:
                yield_count += 1
            status = "✓ Pass" if passed else "✗ Fail"
            print(f"  Result: WNS = {wns:.4f} ns, TNS = {tns:.4f} ns | {status}")
        else:
            print(f"  Result: WNS = N/A, TNS = N/A | ✗ Fail (STA Error)")
        # Optional small delay
        # time.sleep(0.05)

    print("\n--- Monte Carlo Summary ---")
    if wns_list:
        print(f"Successful Runs: {len(wns_list)}/{num_runs}")
        print(f"Average WNS: {np.mean(wns_list):.4f} ns (StdDev: {np.std(wns_list):.4f})")
        print(f"Min WNS:     {np.min(wns_list):.4f} ns")
        print(f"Average TNS: {np.mean(tns_list):.4f} ns (StdDev: {np.std(tns_list):.4f})")
        print(f"Max TNS:     {np.max(tns_list):.4f} ns") # Max TNS (most negative) is worst
        print(f"Timing Yield (WNS>=0 & TNS>=0): {yield_count}/{num_runs} = {100.0 * yield_count / num_runs:.2f}%")
    else:
        print("No valid STA runs completed.")

    # Clean up the last derate file
    if os.path.exists(derate_file):
        try:
            os.remove(derate_file)
        except OSError:
            pass

if __name__ == "__main__":
    # Example usage for standalone MC run:
    # python sta_runner.py my_design.v top_module constraints.sdc stdcell.lib parasitic.spef 20
    import sys
    if len(sys.argv) < 5:
         print("Usage: python sta_runner.py <netlist.v> <design_name> <sdc_file> <lib_file> [spef_file] [num_runs]")
         sys.exit(1)

    netlist_v = sys.argv[1]
    design = sys.argv[2]
    sdc = sys.argv[3]
    lib = sys.argv[4]
    spef = sys.argv[5] if len(sys.argv) > 5 else None
    runs = int(sys.argv[6]) if len(sys.argv) > 6 else 10

    # Check existence before calling
    if not os.path.exists(netlist_v): print(f"Error: Netlist not found: {netlist_v}"); sys.exit(1)
    if not os.path.exists(sdc): print(f"Error: SDC not found: {sdc}"); sys.exit(1)
    if not os.path.exists(lib): print(f"Error: Liberty file not found: {lib}"); sys.exit(1)
    if spef and not os.path.exists(spef): print(f"Warning: SPEF file not found: {spef}"); spef = None # Proceed without SPEF

    monte_carlo_main(verilog_file=netlist_v, num_runs=runs, design_name=design, sdc_path=sdc, lib_path=lib, spef_path=spef)