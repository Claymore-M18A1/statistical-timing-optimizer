import shutil
import os
import math
import random
import subprocess
import time
import sys
import matplotlib.pyplot as plt

# Import necessary functions directly
from sta_runner import run_sta, generate_derate
from perturb import perturb_netlist

# --- Configuration ---
# Files
BASELINE_NETLIST = "design.v"       # Your initial, unmodified netlist
CURRENT_NETLIST = "sa_current.v"    # Netlist representing the current state in SA
CANDIDATE_NETLIST = "sa_candidate.v" # Netlist representing the perturbed state
BEST_NETLIST = "sa_best.v"          # Netlist representing the best solution found so far
DERATE_TCL = "sa_derate.tcl"        # Derate file used during SA evaluation

# STA Setup (Ensure these files exist)
DESIGN_NAME = "gcd" # IMPORTANT: Replace with your actual top-level module name
SDC_FILE = "design.sdc"
LIB_FILE = "my.lib"
SPEF_FILE = "design.spef" # Optional, but highly recommended for accuracy

# SA Parameters
INIT_TEMP = 1.0     # Initial temperature - Adjust based on initial cost variations
FINAL_TEMP = 0.01   # Final temperature - Lower value allows finer tuning at the end
ALPHA = 0.95        # Cooling rate (0.85-0.99). Slower cooling (higher alpha) explores more.
MAX_ITER = 400      # Max iterations per temperature step (or total iterations, depending on loop structure) - Increase significantly
MC_TRIALS = 8      # Number of Monte Carlo STA runs per cost evaluation - Increase for accuracy (e.g., 10-30) but slows down SA.
TNS_WEIGHT = 1.2    # Weight for TNS in the cost function

# Cost function weights
TIMING_WEIGHT = 1  # Weight for timing cost
AREA_WEIGHT = 0    # Weight for area cost

# Area normalization factor (adjust based on your design)
AREA_NORM_FACTOR = 1000.0  # Normalize area to similar scale as timing

# --- Cost Function ---
# --- START OF relevant part of simulated_annealing.py ---
cost_history = []
# ... (other imports and configurations) ...

# --- Cost Function ---
def calculate_area(verilog_path):
    """Calculate total area of the design."""
    try:
        with open(verilog_path, 'r') as f:
            content = f.read()
            
        # Count instances of each cell type and size
        cell_areas = {
            "AND2_X1": 2.0, "AND2_X2": 4.0, "AND2_X4": 8.0,
            "AND3_X1": 3.0, "AND3_X2": 6.0, "AND3_X4": 12.0,
            "AND4_X1": 4.0, "AND4_X2": 8.0, "AND4_X4": 16.0,
            "AOI21_X1": 2.5, "AOI21_X2": 5.0, "AOI21_X4": 10.0,
            "AOI22_X1": 3.0, "AOI22_X2": 6.0, "AOI22_X4": 12.0,
            "BUF_X1": 1.0, "BUF_X2": 2.0, "BUF_X4": 4.0, "BUF_X8": 8.0, "BUF_X16": 16.0, "BUF_X32": 32.0,
            "CLKBUF_X1": 1.5, "CLKBUF_X2": 3.0, "CLKBUF_X3": 4.5,
            "DFF_X1": 5.0, "DFF_X2": 10.0,
            "INV_X1": 1.0, "INV_X2": 2.0, "INV_X4": 4.0, "INV_X8": 8.0, "INV_X16": 16.0, "INV_X32": 32.0,
            "NAND2_X1": 1.5, "NAND2_X2": 3.0, "NAND2_X4": 6.0,
            "NAND3_X1": 2.0, "NAND3_X2": 4.0, "NAND3_X4": 8.0,
            "NAND4_X1": 2.5, "NAND4_X2": 5.0, "NAND4_X4": 10.0,
            "NOR2_X1": 1.5, "NOR2_X2": 3.0, "NOR2_X4": 6.0,
            "NOR3_X1": 2.0, "NOR3_X2": 4.0, "NOR3_X4": 8.0,
            "NOR4_X1": 2.5, "NOR4_X2": 5.0, "NOR4_X4": 10.0,
            "OAI21_X1": 2.5, "OAI21_X2": 5.0, "OAI21_X4": 10.0,
            "OAI22_X1": 3.0, "OAI22_X2": 6.0, "OAI22_X4": 12.0,
            "OR2_X1": 2.0, "OR2_X2": 4.0, "OR2_X4": 8.0,
            "OR3_X1": 2.5, "OR3_X2": 5.0, "OR3_X4": 10.0,
            "OR4_X1": 3.0, "OR4_X2": 6.0, "OR4_X4": 12.0,
            "TBUF_X1": 2.0, "TBUF_X2": 4.0, "TBUF_X4": 8.0, "TBUF_X8": 16.0, "TBUF_X16": 32.0,
            "XNOR2_X1": 3.0, "XNOR2_X2": 6.0,
            "XOR2_X1": 3.0, "XOR2_X2": 6.0
        }
        
        total_area = 0.0
        for cell_type, area in cell_areas.items():
            count = content.count(cell_type)
            total_area += count * area
            
        return total_area
        
    except Exception as e:
        print(f"Error calculating area: {e}")
        return 0.0

def calculate_cost(verilog_path, design_name, sdc_path, lib_path, spef_path=None):
    """Calculate the cost of a solution based on timing and area."""
    print(f"  [Cost] Evaluating {verilog_path} with {MC_TRIALS} MC trials...")
    wns_list = []
    tns_list = []
    successful_trials = 0

    for i in range(MC_TRIALS):
        # Generate new random derates for this trial
        generate_derate(path=DERATE_TCL)
        
        # Run STA
        wns, tns = run_sta(
            verilog_file=verilog_path,
            design_name=design_name,
            sdc_path=sdc_path,
            lib_path=lib_path,
            spef_path=spef_path,
            derate_tcl=DERATE_TCL
        )
        
        if wns is not None and tns is not None:
            wns_list.append(wns)
            tns_list.append(tns)
            successful_trials += 1
            # Print results for this trial
            passed = (wns >= 0 and tns >= 0)
            status = "✓ Pass" if passed else "✗ Fail"
            print(f"    [Trial {i+1:02d}/{MC_TRIALS}] WNS = {wns:+.4f} ns, TNS = {tns:+.4f} ns -> {status}")
        else:
            print(f"    [Trial {i+1:02d}/{MC_TRIALS}] STA Failed")
    
    # Clean up derate file
    if os.path.exists(DERATE_TCL):
        os.remove(DERATE_TCL)
    
    if not successful_trials:
        print("  [Cost] No successful STA trials. Assigning infinite cost.")
        return float('inf')
    
    # Calculate average timing metrics
    avg_wns = sum(wns_list) / successful_trials
    avg_tns = sum(tns_list) / successful_trials
    
    print(f"  [Cost] Average WNS = {avg_wns:+.4f} ns, Average TNS = {avg_tns:+.4f} ns")
    
    # Calculate timing cost (negative values indicate violations)
    timing_cost = 0.0
    if avg_wns < 0:
        timing_cost += abs(avg_wns) * 10.0  # Weight WNS violations more heavily
    if avg_tns < 0:
        timing_cost += abs(avg_tns)
    
    # Calculate area cost
    area = calculate_area(verilog_path)
    area_cost = area / AREA_NORM_FACTOR  # Normalize area to similar scale as timing
    
    # Combine costs with weights
    total_cost = (TIMING_WEIGHT * timing_cost) + (AREA_WEIGHT * area_cost)
    
    print(f"  [Cost] Timing Cost = {timing_cost:.4f}, Area Cost = {area_cost:.4f}, Total Cost = {total_cost:.4f}")
    
    return total_cost

# ... (rest of the simulated_annealing.py code: accept function, SA loop, main block) ...

# --- END OF relevant part of simulated_annealing.py ---

# --- Acceptance Probability ---
def accept(new_cost, old_cost, temp):
    """Metropolis acceptance criterion."""
    if new_cost < old_cost:
        return True # Always accept better solutions
    if temp <= 0: # Avoid division by zero or invalid temp
        return False

    delta = new_cost - old_cost
    # Avoid math domain errors or overflow with large delta/temp
    if delta / temp > 700: # exp(-700) is effectively zero
        probability = 0.0
    else:
        try:
            probability = math.exp(-delta / temp)
        except OverflowError:
            probability = 0.0

    return random.random() < probability

# --- Simulated Annealing Main Loop ---
def simulated_annealing():
    """Performs the simulated annealing optimization."""
    temp = INIT_TEMP
    iteration = 0 # Overall iteration counter

    # --- Initialization ---
    print("[SA Init] Starting Simulated Annealing...")
    # Check required files
    essential_files = [BASELINE_NETLIST, SDC_FILE, LIB_FILE]
    if SPEF_FILE: essential_files.append(SPEF_FILE) # Check optional SPEF too if specified
    for f in essential_files:
        if not os.path.exists(f):
            print(f"[FATAL ERROR] Required file not found: {f}. Exiting.")
            sys.exit(1)

    # Clean up previous run files (optional but recommended)
    for f in [CURRENT_NETLIST, CANDIDATE_NETLIST, BEST_NETLIST, DERATE_TCL]:
        if os.path.exists(f):
            os.remove(f)

    # Copy baseline to current and best to start
    try:
        shutil.copy(BASELINE_NETLIST, CURRENT_NETLIST)
        shutil.copy(BASELINE_NETLIST, BEST_NETLIST)
    except Exception as e:
        print(f"[FATAL ERROR] Failed to copy baseline netlist: {e}. Exiting.")
        sys.exit(1)

    # Calculate initial cost
    print("[SA Init] Calculating initial cost...")
    current_cost = calculate_cost(CURRENT_NETLIST, DESIGN_NAME, SDC_FILE, LIB_FILE, SPEF_FILE)
    if current_cost == float('inf'):
        print("[FATAL ERROR] Initial baseline netlist failed STA. Cannot proceed. Check baseline files and setup.")
        sys.exit(1)

    best_cost = current_cost
    print(f"[SA Init] Initial Cost (Baseline) = {current_cost:.6f}")

    # --- SA Loop ---
    max_total_iterations = MAX_ITER * int(math.log(FINAL_TEMP/INIT_TEMP) / math.log(ALPHA)) if ALPHA < 1 else MAX_ITER*100
    print(f"[SA RUN] Estimated total iterations ~{max_total_iterations}")

    while temp > FINAL_TEMP and iteration < max_total_iterations : # Added total iteration limit
        iteration += 1
        print(f"\n[Iter {iteration}] Temp = {temp:.6f}")

        # 1. Perturb: Generate a candidate solution from the current one
        print(f"  [Perturb] Generating candidate from {CURRENT_NETLIST}")
        perturbed_path = perturb_netlist(CURRENT_NETLIST, CANDIDATE_NETLIST)

        if perturbed_path is None:
            print("  [!] Perturbation failed. Skipping this iteration.")
            # Optionally cool down anyway, or retry perturbation
            # temp *= ALPHA # Example: Cool down even on failure
            continue

        # 2. Evaluate: Calculate the cost of the candidate solution
        candidate_cost = calculate_cost(CANDIDATE_NETLIST, DESIGN_NAME, SDC_FILE, LIB_FILE, SPEF_FILE)
        print(f"  [Evaluate] Current Cost = {current_cost:.6f}, Candidate Cost = {candidate_cost:.6f}")

        # 3. Decide: Accept or reject the candidate
        if accept(candidate_cost, current_cost, temp):
            print("  [Accept] ✓ Accepted Candidate")
            current_cost = candidate_cost
            try:
                shutil.copy(CANDIDATE_NETLIST, CURRENT_NETLIST) # Update current state
            except Exception as e:
                 print(f"  [Warning] Failed to copy candidate to current: {e}")


            # Check if this is the best solution found so far
            if current_cost < best_cost:
                print(f"  [Best]   🚀 New Best Found! Cost = {current_cost:.6f}")
                best_cost = current_cost
                try:
                    shutil.copy(CURRENT_NETLIST, BEST_NETLIST) # Save the new best
                except Exception as e:
                    print(f"  [Warning] Failed to copy current to best: {e}")
        else:
            print("  [Reject] ✗ Rejected Candidate")
            # Current state remains unchanged (CURRENT_NETLIST and current_cost)

        # 4. Cool down (typically after a fixed number of iterations at a temp,
        # or after each iteration as done here)
        # This implementation cools every iteration, which is simpler.
        # A common alternative is to run MAX_ITER iterations *per temperature step*.
        temp *= ALPHA
        # time.sleep(0.01) # Optional small delay
        cost_history.append(current_cost)

        # Clean up candidate file (optional, saves disk space)
        # if os.path.exists(CANDIDATE_NETLIST): os.remove(CANDIDATE_NETLIST)

# ... inside simulated_annealing function, after SA loop finishes ...

    # --- End of SA ---
    print(f"\n[SA Done] Simulated Annealing Finished.")
    print(f"  Final Temperature = {temp:.6f}")
    # print(f"  Total Iterations = {total_iterations}") # Assuming you used the modified loop
    print(f"  Total Iterations = {iteration}") # If you used the original loop structure
    # print(f"  Total Iterations = {iteration}") # If you used the original loop structure
    print(f"  Best Cost Found = {best_cost:.6f}")
    print(f"  Best netlist saved to: {BEST_NETLIST}")

    # --- Final Comparison ---
    print("\n[Info] Comparing Initial Baseline vs Final Best Netlist (Nominal STA)...")

    # Run nominal STA (no derates) for Baseline
    print("\n🟢 Baseline (Initial) Nominal STA:")
    generate_derate(path=DERATE_TCL, mu=1.0, sigma_delay=0, sigma_check=0) # Nominal
    wns_base, tns_base = run_sta(BASELINE_NETLIST, DESIGN_NAME, SDC_FILE, LIB_FILE, SPEF_FILE, DERATE_TCL)
    if wns_base is not None:
        print(f"  Nominal WNS (Baseline) = {wns_base:+.4f} ns")
        print(f"  Nominal TNS (Baseline) = {tns_base:+.4f} ns")
    else:
        print("  Nominal STA failed for Baseline.")
        wns_base, tns_base = None, None # Ensure they are None for diff calculation


    # Run nominal STA for Best
    print("\n🔵 Best (Final) Nominal STA:")
    if not os.path.exists(BEST_NETLIST):
        print("  [Error] Best netlist file not found. Cannot perform final evaluation.")
        wns_best, tns_best = None, None # Ensure they are None
    else:
        generate_derate(path=DERATE_TCL, mu=1.0, sigma_delay=0, sigma_check=0) # Nominal
        wns_best, tns_best = run_sta(BEST_NETLIST, DESIGN_NAME, SDC_FILE, LIB_FILE, SPEF_FILE, DERATE_TCL)
        if wns_best is not None:
            print(f"  Nominal WNS (Best) = {wns_best:+.4f} ns")
            print(f"  Nominal TNS (Best) = {tns_best:+.4f} ns")
        else:
            print("  Nominal STA failed for Best.")
            wns_best, tns_best = None, None # Ensure they are None

    # --- Calculate and Print Differences ---
    print("\n📊 Performance Comparison (Best vs Baseline):")
    if wns_base is not None and wns_best is not None:
        wns_diff = wns_best - wns_base
        wns_improvement = (wns_diff > 0) # Higher WNS is better
        wns_status = '(Improved)' if wns_improvement else '(Worsened or No Change)'
        print(f"  WNS Difference: {wns_diff:+.4f} ns {wns_status}")
    else:
        wns_diff = None
        wns_status = 'N/A (STA failed for baseline or best)'
        print("  WNS Difference: N/A (STA failed for baseline or best)")

    if tns_base is not None and tns_best is not None:
        tns_diff = tns_best - tns_base
        tns_improvement = (tns_diff > 0) if tns_base < 0 else (tns_best >= 0)
        tns_status = "N/A"
        if tns_base < 0:
            if tns_best > tns_base: tns_status = '(Improved)'
            else: tns_status = '(Worsened or No Change)'
        else:
            if tns_best >= 0: tns_status = '(Maintained)'
            else: tns_status = '(Worsened - Became Negative!)'
        print(f"  TNS Difference: {tns_diff:+.4f} ns {tns_status}")
    else:
        tns_diff = None
        tns_status = 'N/A (STA failed for baseline or best)'
        print("  TNS Difference: N/A (STA failed for baseline or best)")

    # Clean up the last derate file
    if os.path.exists(DERATE_TCL):
        try:
            os.remove(DERATE_TCL)
        except OSError:
            pass

    # Save SA Cost Curve
    plt.plot(cost_history)
    plt.xlabel("Iteration")
    plt.ylabel("Cost")
    plt.title("SA Cost over Iterations")
    plt.grid(True)
    plt.tight_layout()

    # --- Add performance summary as text on the plot ---
    summary_lines = [
        "Performance Comparison (Best vs Baseline):",
        f"Baseline: WNS={wns_base if wns_base is not None else 'N/A'} ns, TNS={tns_base if tns_base is not None else 'N/A'} ns",
        f"Best:     WNS={wns_best if 'wns_best' in locals() and wns_best is not None else 'N/A'} ns, TNS={tns_best if 'tns_best' in locals() and tns_best is not None else 'N/A'} ns",
        f"WNS Diff: {wns_diff if wns_diff is not None else 'N/A'} ns {wns_status}",
        f"TNS Diff: {tns_diff if tns_diff is not None else 'N/A'} ns {tns_status}"
    ]
    summary_text = "\n".join(summary_lines)
    # Place the text at the bottom left of the plot
    plt.gca().text(0.01, 0.01, summary_text, transform=plt.gca().transAxes,
                   fontsize=8, va='bottom', ha='left', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))

    # --- Save plot with SA parameters in filename, in 'results' folder ---
    results_dir = "results"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    plot_filename = f"sa_cost_curve_INIT_TEMP-{INIT_TEMP}_FINAL_TEMP-{FINAL_TEMP}_ALPHA-{ALPHA}_MAX_ITER-{MAX_ITER}.png"
    plot_path = os.path.join(results_dir, plot_filename)
    plt.savefig(plot_path)
    print(f"Saved cost plot as {plot_path}")


# --- Main Execution ---
if __name__ == "__main__":
    simulated_annealing()