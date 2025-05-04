import numpy as np
import subprocess
import time
import re
import os

# --- Utility Functions for STA ---

def generate_derate(path="derate.tcl", mu=1.0, sigma_delay=0.03, sigma_check=0.02):
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
            f.write(f"link_design {design_name}\n") # Use design name variable
            f.write(f"read_sdc {sdc_path}\n")
            # SPEF reading is crucial for accuracy, ensure it exists if uncommented
            if spef_path and os.path.exists(spef_path):
                 f.write(f"read_spef {spef_path}\n")
            else:
                 print(f"[Warning] SPEF file '{spef_path}' not found or specified, skipping read_spef.")
            # Source the derate file
            if derate_tcl and os.path.exists(derate_tcl):
                f.write(f"source {derate_tcl}\n")
            else:
                print(f"[Warning] Derate file '{derate_tcl}' not found or specified, skipping derate source.")

            # Ensure reports are written even if timing fails partially
            f.write(f"report_checks -path_delay max -sort_by_slack > {timing_report}\n")
            f.write(f"report_wns > {wns_report}\n")
            f.write(f"report_tns > {tns_report}\n")
            f.write("exit\n")
        return True
    except IOError as e:
        print(f"[ERROR] Failed to write Tcl script {tcl_path}: {e}")
        return False

def parse_timing_report(path="timing.txt", keyword="slack (VIOLATED)"):
    """Parses a timing report file for a specific keyword value."""
    try:
        with open(path, 'r') as f:
            for line in f:
                # Updated regex to handle potential variations in spacing and case
                match = re.search(rf'{keyword}\s+([-\d\.e+]+)', line, re.IGNORECASE)
                if match:
                    return float(match.group(1))
        # If keyword not found, maybe timing is met or format changed
        # Try parsing for non-violated slack as a fallback
        with open(path, 'r') as f:
            for line in f:
                 match = re.search(r'slack \(MET\)\s+([-\d\.e+]+)', line, re.IGNORECASE)
                 if match:
                     return float(match.group(1)) # Return the positive slack

    except FileNotFoundError:
        print(f"[Warning] Timing report file not found: {path}")
    except ValueError:
        print(f"[Warning] Could not parse float from timing report: {path}")
    except Exception as e:
        print(f"[Warning] Failed to parse timing report {path}: {e}")
    return None # Indicate failure or inability to parse

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
    """
    Runs OpenSTA using a generated Tcl script and parses WNS/TNS.

    Args:
        verilog_file (str): Path to the Verilog netlist.
        design_name (str): Name of the top-level module.
        sdc_path (str): Path to the SDC constraints file.
        lib_path (str): Path to the Liberty library file.
        spef_path (str): Path to the SPEF parasitic file (optional).
        derate_tcl (str): Path to the derate Tcl file (optional, needed for MC).

    Returns:
        tuple: (wns, tns) or (None, None) if STA fails or parsing fails.
    """
    tcl_script = "run_sta_temp.tcl" # Use a temporary name
    timing_report = "timing_temp.txt"
    wns_report = "wns_temp.txt"
    tns_report = "tns_temp.txt"

    # Generate the Tcl script for this specific run
    if not generate_run_tcl(tcl_path=tcl_script, verilog_path=verilog_file, design_name=design_name, sdc_path=sdc_path, lib_path=lib_path, spef_path=spef_path, derate_tcl=derate_tcl, timing_report=timing_report, wns_report=wns_report, tns_report=tns_report):
        print("[ERROR] Failed to generate STA Tcl script.")
        return None, None

    # Define the command to run OpenSTA
    cmd = ["opensta", "-exit", tcl_script]
    # print(f"  [STA CMD] Running: {' '.join(cmd)}") # Optional Debug

    try:
        # Run OpenSTA
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60) # Add timeout

        # Filter common OpenSTA header/license lines for cleaner output
        filtered_output = "\n".join([
            line for line in (result.stdout + result.stderr).splitlines()
            if not line.startswith("OpenSTA") and
               not line.startswith("Copyright") and
               not line.startswith("This is free software") and
               "License GPLv3" not in line and
               "ABSOLUTELY NO WARRANTY" not in line and
               "http://gnu.org" not in line and
               "for details." not in line and
               not line.strip() == "" # Remove empty lines too
        ])
        if filtered_output:
             # Indent STA output slightly for clarity in SA log
             print("    --- OpenSTA Output ---")
             for line in filtered_output.splitlines():
                 print(f"    {line}")
             print("    --- End OpenSTA Output ---")


        # Check for OpenSTA errors
        if result.returncode != 0:
            print(f"[ERROR] OpenSTA execution failed for {verilog_file} with return code {result.returncode}.")
            # print(f"  stderr:\n{result.stderr}") # Keep stderr for debugging
            return None, None
        if "Error:" in result.stdout or "Error:" in result.stderr:
             print(f"[ERROR] OpenSTA reported errors during execution for {verilog_file}.")
             return None, None


        # Parse the results
        wns = parse_wns(wns_report)
        tns = parse_tns(tns_report)

        # Basic validation
        if wns is None or tns is None:
             print(f"[ERROR] Failed to parse WNS or TNS from reports for {verilog_file}.")
             # Optionally try parsing the main timing report as a last resort
             # wns = parse_timing_report(timing_report) # This might get the worst slack
             # tns = None # TNS is harder to get from the main report reliably
             return None, None

        return wns, tns

    except subprocess.TimeoutExpired:
        print(f"[ERROR] OpenSTA timed out for {verilog_file}.")
        return None, None
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred while running/parsing STA for {verilog_file}: {e}")
        return None, None
    finally:
        # Clean up temporary files
        for f in [tcl_script, timing_report, wns_report, tns_report]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass # Ignore cleanup errors

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