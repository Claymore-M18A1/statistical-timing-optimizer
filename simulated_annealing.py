import shutil
import os
import math
import random
import subprocess
import time
import sys

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
FINAL_TEMP = 1e-2   # Final temperature - Lower value allows finer tuning at the end
ALPHA = 0.9        # Cooling rate (0.85-0.99). Slower cooling (higher alpha) explores more.
MAX_ITER = 200      # Max iterations per temperature step (or total iterations, depending on loop structure) - Increase significantly
MC_TRIALS = 3      # Number of Monte Carlo STA runs per cost evaluation - Increase for accuracy (e.g., 10-30) but slows down SA.
TNS_WEIGHT = 0.1    # Weight for TNS in the cost function

# --- Cost Function ---
# --- START OF relevant part of simulated_annealing.py ---

# ... (other imports and configurations) ...

# --- Cost Function ---
def cost_function(netlist_path):
    """
    Calculates the cost of a given netlist using Monte Carlo STA.
    Lower cost is better. Cost focuses on timing violations.
    """
    wns_list = []
    tns_list = []
    print(f"  [Cost] Evaluating {netlist_path} with {MC_TRIALS} MC trials...")
    successful_trials = 0

    required_files = [netlist_path, SDC_FILE, LIB_FILE]
    # Check SPEF existence once outside the loop
    spef_exists = SPEF_FILE and os.path.exists(SPEF_FILE)
    if SPEF_FILE and not spef_exists:
        print(f"    [Warning] SPEF file '{SPEF_FILE}' not found. STA accuracy reduced.")

    for i in range(MC_TRIALS):
        # 1. Generate new random derates for this trial
        generate_derate(path=DERATE_TCL) # Overwrites the file each time

        # 2. Run STA
        # Make sure run_sta uses the correct derate file
        wns, tns = run_sta(verilog_file=netlist_path,
                           design_name=DESIGN_NAME,
                           sdc_path=SDC_FILE,
                           lib_path=LIB_FILE,
                           spef_path=SPEF_FILE if spef_exists else None,
                           derate_tcl=DERATE_TCL)

        # 3. Process results
        if wns is not None and tns is not None:
            wns_list.append(wns)
            tns_list.append(tns)
            successful_trials += 1
            # --- ADDED PRINT STATEMENT ---
            # Determine pass/fail status for this specific trial
            passed = (wns >= 0 and tns >= 0) # Or just wns >= 0 depending on your criteria
            status = "✓ Pass" if passed else "✗ Fail"
            # Print the details for this trial
            print(f"    [Trial {i+1:02d}/{MC_TRIALS}] WNS = {wns:+.4f}, TNS = {tns:+.4f} -> {status}")
            # --- END OF ADDED PRINT ---
        else:
            # STA failed for this trial
            print(f"    [Trial {i+1:02d}/{MC_TRIALS}] STA Failed for {netlist_path}. Assigning infinite cost.")
            # Clean up derate file if it exists
            if os.path.exists(DERATE_TCL): os.remove(DERATE_TCL)
            return float('inf') # Penalize heavily

    # Clean up the last derate file
    if os.path.exists(DERATE_TCL): os.remove(DERATE_TCL)

    # Calculate cost based on successful trials
    if not successful_trials:
        print(f"    [!] No successful STA trials for {netlist_path}. Assigning infinite cost.")
        return float('inf')

    # Cost Calculation (using average, penalizing negative)
    avg_wns = sum(wns_list) / successful_trials
    avg_tns = sum(tns_list) / successful_trials

    cost = 1e-6 # Base cost
    cost += max(0, -avg_wns)
    cost += TNS_WEIGHT * max(0, -avg_tns)

    print(f"    [Cost OK] Avg WNS={avg_wns:.4f}, Avg TNS={avg_tns:.4f} -> Cost={cost:.6f}")
    return cost

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
    current_cost = cost_function(CURRENT_NETLIST)
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
        candidate_cost = cost_function(CANDIDATE_NETLIST)

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
        print(f"  WNS Difference: {wns_diff:+.4f} ns {'(Improved 👍)' if wns_improvement else '(Worsened 👎 or No Change)'}")
    else:
        print("  WNS Difference: N/A (STA failed for baseline or best)")

    if tns_base is not None and tns_best is not None:
        # TNS is Total Negative Slack, closer to 0 (or positive) is better
        tns_diff = tns_best - tns_base
        # Improvement means TNS increased (became less negative or more positive)
        tns_improvement = (tns_diff > 0) if tns_base < 0 else (tns_best >= 0) # Consider if baseline was already non-negative
        # More nuanced check for TNS improvement:
        # If baseline TNS was negative, improvement means best TNS is less negative (larger value).
        # If baseline TNS was non-negative, improvement means best TNS is also non-negative.
        tns_status = "N/A"
        if tns_base < 0:
            if tns_best > tns_base: tns_status = '(Improved 👍)'
            else: tns_status = '(Worsened 👎 or No Change)'
        else: # tns_base >= 0
            if tns_best >= 0: tns_status = '(Maintained ✅)'
            else: tns_status = '(Worsened 👎 - Became Negative!)'

        print(f"  TNS Difference: {tns_diff:+.4f} ns {tns_status}")
    else:
        print("  TNS Difference: N/A (STA failed for baseline or best)")


    # Clean up the last derate file
    if os.path.exists(DERATE_TCL):
        try:
            os.remove(DERATE_TCL)
        except OSError:
            pass

# --- Main Execution ---
if __name__ == "__main__":
    simulated_annealing()