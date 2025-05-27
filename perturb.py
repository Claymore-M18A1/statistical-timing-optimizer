import random
import re
import sys
import time
import os # For diff command in test
import subprocess
import json
from collections import defaultdict
from sta_runner import run_sta, generate_derate, parse_timing_report

# --- Configuration ---

# Maximum number of gates to modify in a single call to perturb_netlist
MAX_GATES_TO_MODIFY_PER_RUN = 10 # <<< ADJUST THIS VALUE AS NEEDED (e.g., 1, 3, 5, 10)

# More granular sizing targets based on the grep output
SIZING_TARGETS_PER_CELL = {
    "AND2_X":   {1: [2],    2: [1, 4], 4: [1, 2]},
    "AND3_X":   {1: [2],    2: [1, 4], 4: [1, 2]},
    "AND4_X":   {1: [2],    2: [1, 4], 4: [1, 2]},
    "AOI21_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "AOI22_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "AOI211_X": {1: [2],    2: [1, 4], 4: [1, 2]},
    "AOI221_X": {1: [2],    2: [1, 4], 4: [1, 2]},
    "AOI222_X": {1: [2],    2: [1, 4], 4: [1, 2]},
    "BUF_X":    {1: [2],    2: [1, 4], 4: [1, 2, 8], 8: [2, 4, 16], 16: [4, 8, 32], 32: [8, 16]},
    "CLKBUF_X": {1: [2],    2: [1, 3], 3: [1, 2]},
    "DFF_X":    {1: [2],    2: [1]},
    "DFFR_X":   {1: [2],    2: [1]},
    "DFFS_X":   {1: [2],    2: [1]},
    "DFFRS_X":  {1: [2],    2: [1]},
    "SDFF_X":   {1: [2],    2: [1]},
    "SDFFR_X":  {1: [2],    2: [1]},
    "SDFFS_X":  {1: [2],    2: [1]},
    "SDFFRS_X": {1: [2],    2: [1]},
    "DLH_X":    {1: [2],    2: [1]},
    "DLL_X":    {1: [2],    2: [1]},
    "INV_X":    {1: [2],    2: [1, 4], 4: [1, 2, 8], 8: [2, 4, 16], 16: [4, 8, 32], 32: [8, 16]},
    "MUX2_X":   {1: [2],    2: [1]},
    "NAND2_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "NAND3_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "NAND4_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "NOR2_X":   {1: [2],    2: [1, 4], 4: [1, 2]},
    "NOR3_X":   {1: [2],    2: [1, 4], 4: [1, 2]},
    "NOR4_X":   {1: [2],    2: [1, 4], 4: [1, 2]},
    "OAI21_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "OAI22_X":  {1: [2],    2: [1, 4], 4: [1, 2]},
    "OAI33_X":  {1: []},
    "OAI211_X": {1: [2],    2: [1, 4], 4: [1, 2]},
    "OAI221_X": {1: [2],    2: [1, 4], 4: [1, 2]},
    "OAI222_X": {1: [2],    2: [1, 4], 4: [1, 2]},
    "OR2_X":    {1: [2],    2: [1, 4], 4: [1, 2]},
    "OR3_X":    {1: [2],    2: [1, 4], 4: [1, 2]},
    "OR4_X":    {1: [2],    2: [1, 4], 4: [1, 2]},
    "TBUF_X":   {1: [2],    2: [1, 4], 4: [1, 2, 8], 8: [2, 4, 16], 16: [4, 8]},
    "TINV_X":   {1: []},
    "XNOR2_X":  {1: [2],    2: [1]},
    "XOR2_X":   {1: [2],    2: [1]},
}

# Probability applied AFTER a potentially sizable gate is matched and limit allows.
# This controls how likely a potential modification actually happens.
PROB_APPLY_SIZE_CHANGE = 0.95 # High chance to apply change once identified & within limit

SIZABLE_CELL_BASES = set(SIZING_TARGETS_PER_CELL.keys())

REGEX_PATTERN_TEMPLATE = r'([A-Z0-9_]+?)({suffix})(\d+)(\s+)([a-zA-Z_]\w*)(\s*\()'
CELL_SUFFIX = "X"

EXISTING_SIZES = set(sz for targets in SIZING_TARGETS_PER_CELL.values() for sz in targets.keys())
ALL_TARGET_SIZES = set(tsz for targets in SIZING_TARGETS_PER_CELL.values() for sz_targets in targets.values() for tsz in sz_targets)
ALL_KNOWN_SIZES = sorted(list(EXISTING_SIZES.union(ALL_TARGET_SIZES)))

REGEX_PATTERNS = {}
for size in ALL_KNOWN_SIZES:
     pattern_string = REGEX_PATTERN_TEMPLATE.format(suffix=re.escape(CELL_SUFFIX), size=size)
     REGEX_PATTERNS[size] = re.compile(pattern_string)

# Add timing-related configuration
CRITICAL_PATH_THRESHOLD = -0.1  # Paths with slack less than this are considered critical
SLACK_SENSITIVITY_THRESHOLD = 0.2  # Gates with slack sensitivity above this are prioritized

def get_timing_info(verilog_path, design_name, sdc_file, lib_file, spef_file=None):
    """Get timing information from STA to identify critical paths and slack sensitivity."""
    # Initialize timing analysis data structures
    critical_paths = set()
    slack_sensitivity = defaultdict(float)
    gate_fanout = defaultdict(int)
    gate_location = defaultdict(str)
    cell_timing = defaultdict(dict)
    
    try:
        # Run STA to get timing information
        wns, tns = run_sta(
            verilog_file=verilog_path,
            design_name=design_name,
            sdc_path=sdc_file,
            lib_path=lib_file,
            spef_path=spef_file
        )
        
        if wns is None or tns is None:
            print("  [Warning] Failed to get timing information, falling back to random selection")
            return set(), defaultdict(float), defaultdict(int), defaultdict(str), defaultdict(dict)
        
        # Read the verilog file to get gate information
        with open(verilog_path, 'r') as f:
            content = f.readlines()
            
        # Enhanced pattern matching for gates with more detailed timing analysis
        gate_pattern = re.compile(r'(\w+)_X(\d+)\s+(\w+)\s*\(')
        
        # Track gate connections for better path analysis
        gate_connections = defaultdict(set)
        gate_inputs = defaultdict(set)
        gate_outputs = defaultdict(set)
        
        # First pass: build connection graph
        for line in content:
            match = gate_pattern.search(line)
            if match:
                cell_type = match.group(1)
                size = int(match.group(2))
                instance_name = match.group(3)
                
                # Parse connections from the line
                connections = re.findall(r'\.(\w+)\s*\(\s*(\w+)\s*\)', line)
                for port, net in connections:
                    if port.startswith('I'):  # Input port
                        gate_inputs[instance_name].add(net)
                    elif port.startswith('Z'):  # Output port
                        gate_outputs[instance_name].add(net)
        
        # Second pass: analyze timing characteristics
        for line in content:
            match = gate_pattern.search(line)
            if match:
                cell_type = match.group(1)
                size = int(match.group(2))
                instance_name = match.group(3)
                
                # Get timing information from STA report
                timing_info = parse_timing_report("timing.txt")
                gate_timing = timing_info.get(instance_name, {})
                
                # Calculate timing metrics based on STA results
                if wns < 0:  # If there are timing violations
                    # Base criticality calculation using actual timing data
                    criticality = abs(gate_timing.get('slack', wns))
                    
                    # Adjust criticality based on cell type and size
                    if cell_type in ['AND', 'NAND', 'OR', 'NOR', 'AOI', 'OAI']:
                        criticality *= (1.2 + size * 0.1)  # Larger logic gates are more critical
                        gate_location[instance_name] = "middle"
                    elif cell_type in ['BUF', 'INV', 'CLKBUF']:
                        criticality *= (0.8 + size * 0.15)  # Larger buffers are more critical
                        gate_location[instance_name] = "end"
                    elif cell_type in ['DFF', 'LATCH']:
                        criticality *= (1.5 + size * 0.2)  # Larger sequential elements are more critical
                        gate_location[instance_name] = "sequential"
                    
                    # Adjust criticality based on actual delay and slew
                    delay = gate_timing.get('delay', 0.0)
                    slew = gate_timing.get('slew', 0.0)
                    if delay > 0:
                        criticality *= (1.0 + delay / abs(wns))  # Higher delay increases criticality
                    if slew > 0:
                        criticality *= (1.0 + slew / abs(wns))  # Higher slew increases criticality
                    
                    # Adjust criticality based on fanout
                    fanout = len(gate_outputs[instance_name])
                    if fanout > 0:
                        criticality *= (1.0 + min(fanout / 5.0, 1.0))  # Higher fanout increases criticality
                    
                    # Adjust criticality based on input connections
                    input_count = len(gate_inputs[instance_name])
                    if input_count > 0:
                        criticality *= (1.0 + input_count * 0.1)  # More inputs can increase criticality
                    
                    # Add to critical paths if criticality is significant
                    if criticality > abs(wns) * 0.5:
                        critical_paths.add(instance_name)
                        slack_sensitivity[instance_name] = criticality
                
                # Enhanced fanout estimation
                if cell_type in ['BUF', 'INV', 'CLKBUF']:
                    gate_fanout[instance_name] = size * 2  # Buffers typically drive more loads
                elif cell_type in ['DFF', 'LATCH']:
                    gate_fanout[instance_name] = 1  # Sequential elements typically drive one load
                else:
                    gate_fanout[instance_name] = max(2, size)  # Logic gates have at least 2 fanouts
                
                # Enhanced cell timing characteristics using actual STA data
                cell_timing[instance_name] = {
                    "delay": gate_timing.get('delay', size * 0.1),  # Use actual delay if available
                    "slew": gate_timing.get('slew', size * 0.05),  # Use actual slew if available
                    "capacitance": size * 0.2,  # Base capacitance
                    "setup_time": 0.1 if cell_type in ['DFF', 'LATCH'] else 0.0,  # Setup time for sequential elements
                    "hold_time": 0.05 if cell_type in ['DFF', 'LATCH'] else 0.0,  # Hold time for sequential elements
                    "clock_to_q": 0.15 if cell_type in ['DFF', 'LATCH'] else 0.0,  # Clock-to-Q delay for sequential elements
                    "input_count": len(gate_inputs[instance_name]),  # Number of inputs
                    "output_count": len(gate_outputs[instance_name]),  # Number of outputs
                    "path_type": gate_timing.get('path_type', 'unknown')  # Path type from STA
                }
        
        return critical_paths, slack_sensitivity, gate_fanout, gate_location, cell_timing
        
    except Exception as e:
        print(f"  [Warning] Error in timing analysis: {e}")
        return set(), defaultdict(float), defaultdict(int), defaultdict(str), defaultdict(dict)

def get_gate_score(gate_name, critical_paths, slack_sensitivity, gate_fanout, gate_location, cell_timing):
    """Calculate a score for a gate based on timing factors only."""
    score = 0.0
    needs_upsize = False  # Flag to indicate if this gate should be upsized
    
    # Get the slack for this gate
    slack = slack_sensitivity.get(gate_name, 0.0)
    
    # 1. Critical path contribution
    if gate_name in critical_paths:
        score += 5.0  # Much higher weight for critical path gates
        # For setup violations (negative slack), we want to upsize
        needs_upsize = True  # Always upsize critical path gates
    
    # 2. Slack sensitivity contribution
    score += abs(slack) * 5.0  # Much higher weight for slack sensitivity
    if slack < 0:  # Any setup violation
        needs_upsize = True  # Always upsize for setup violations
    
    # 3. Position in path contribution
    position = gate_location.get(gate_name, "")
    if position == "middle":
        score *= 3.0  # Much higher weight for middle gates
        needs_upsize = True  # Always upsize middle gates
    elif position == "end":
        score *= 2.0  # Higher weight for end gates
        needs_upsize = True  # Always upsize end gates
    
    # 4. Cell timing characteristics
    timing_info = cell_timing.get(gate_name, {})
    if timing_info:
        # Consider delay and slew
        delay = timing_info.get("delay", 0)
        slew = timing_info.get("slew", 0)
        
        # Higher weight for gates with poor timing
        if delay > 0.1:
            score *= (1.0 + delay * 3.0)
            needs_upsize = True
        if slew > 0.1:
            score *= (1.0 + slew * 3.0)
            needs_upsize = True
    
    # 5. Special handling for buffers and clock gates
    if "buf" in gate_name.lower() or "clk" in gate_name.lower():
        score *= 2.0  # Give higher priority to buffers and clock gates
        needs_upsize = True  # Always upsize buffers and clock gates
    
    return score, needs_upsize

def select_new_size(current_size, possible_sizes, needs_upsize):
    """Select a new size based on timing needs."""
    if not possible_sizes:
        return current_size
        
    if needs_upsize:
        # For setup violations, consider larger sizes
        larger_sizes = [s for s in possible_sizes if s > current_size]
        if larger_sizes:
            # 95% chance to upsize to the largest possible size
            if random.random() < 0.95:
                return max(larger_sizes)
            else:
                # 5% chance to choose a random larger size
                return random.choice(larger_sizes)
        else:
            return current_size  # Keep current size if no larger options
    else:
        # For hold violations, consider smaller sizes
        smaller_sizes = [s for s in possible_sizes if s < current_size]
        if smaller_sizes:
            # 80% chance to downsize
            if random.random() < 0.8:
                return random.choice(smaller_sizes)
            else:
                # 20% chance to keep current size
                return current_size
        else:
            return current_size  # Keep current size if no smaller options

# --- Perturbation Function ---
def perturb_netlist(verilog_path, new_path):
    try:
        with open(verilog_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"[ERROR] Input netlist not found: {verilog_path}")
        return None

    # Get timing information
    critical_paths, slack_sensitivity, gate_fanout, gate_location, cell_timing = get_timing_info(
        verilog_path, 
        "gcd",  # Replace with your design name
        "design.sdc",
        "my.lib",
        "design.spef" if os.path.exists("design.spef") else None
    )
    
    print(f"  [Timing Info] Found {len(critical_paths)} gates on critical paths")
    
    perturbed_lines = []
    gates_sized_count = 0
    buffer_inserted = False
    gates_modified_this_run = 0

    # --- Create a list of potential modification points with scores ---
    potential_mods = []  # Store tuples: (line_index, current_size, match_object, score, needs_upsize)
    for line_num, line in enumerate(lines):
        for current_size, pattern in REGEX_PATTERNS.items():
            match = pattern.search(line)
            if match:
                cell_name_base = match.group(1)
                cell_suffix_matched = match.group(2)
                instance_name = match.group(5)
                full_base = cell_name_base + cell_suffix_matched
                
                if full_base in SIZABLE_CELL_BASES:
                    targets_for_this_cell = SIZING_TARGETS_PER_CELL.get(full_base)
                    if targets_for_this_cell:
                        possible_new_sizes = targets_for_this_cell.get(current_size)
                        if possible_new_sizes:
                            # Calculate score for this gate
                            score, needs_upsize = get_gate_score(
                                instance_name, critical_paths, slack_sensitivity,
                                gate_fanout, gate_location, cell_timing
                            )
                            potential_mods.append((line_num, current_size, match, score, needs_upsize))

    # Sort potential modifications by score (highest first)
    potential_mods.sort(key=lambda x: x[3], reverse=True)
    
    lines_to_modify_indices = set()

    for line_index, current_size, match, score, needs_upsize in potential_mods:
        if gates_modified_this_run >= MAX_GATES_TO_MODIFY_PER_RUN:
            break

        if line_index in lines_to_modify_indices:
            continue

        # Adjust probability based on score
        adjusted_prob = PROB_APPLY_SIZE_CHANGE * (1.0 + score)  # Increase probability for high-scoring gates
        if random.random() < adjusted_prob:
            cell_name_base = match.group(1)
            cell_suffix_matched = match.group(2)
            whitespace_after_size = match.group(4)
            instance_name = match.group(5)
            space_and_paren = match.group(6)
            full_base = cell_name_base + cell_suffix_matched

            targets_for_this_cell = SIZING_TARGETS_PER_CELL.get(full_base)
            if targets_for_this_cell:
                possible_new_sizes = targets_for_this_cell.get(current_size)
                if possible_new_sizes:
                    # Select new size based on timing needs
                    new_size = select_new_size(current_size, possible_new_sizes, needs_upsize)
                    
                    if new_size != current_size:  # Only modify if size actually changes
                        original_line = lines[line_index]
                        modified_line = match.re.sub(
                            f"{cell_name_base}{cell_suffix_matched}{new_size}{whitespace_after_size}{instance_name}{space_and_paren}",
                            original_line,
                            count=1
                        )

                        if modified_line != original_line:
                            lines[line_index] = modified_line
                            gates_sized_count += 1
                            gates_modified_this_run += 1
                            lines_to_modify_indices.add(line_index)
                            size_change = "upsize" if new_size > current_size else "downsize"
                            print(f"  [Perturb] Modified gate {instance_name} (Score: {score:.2f}, {size_change} {current_size}->{new_size})")

    perturbed_lines = lines

    try:
        with open(new_path, 'w') as f:
            f.writelines(perturbed_lines)
        print(f"  [Perturb OK] Saved to {new_path}. Gates sized: {gates_sized_count} (Limit: {MAX_GATES_TO_MODIFY_PER_RUN})")
        if gates_sized_count == 0 and len(potential_mods) > 0:
            print(f"  [Perturb INFO] No gates were sized (Prob: {PROB_APPLY_SIZE_CHANGE}, Limit: {MAX_GATES_TO_MODIFY_PER_RUN}). Potential mods found: {len(potential_mods)}")
        elif gates_sized_count == 0 and len(potential_mods) == 0:
            print("  [Perturb WARNING] No sizable gates found matching patterns/config.")
        return new_path
    except IOError as e:
        print(f"[ERROR] Could not write perturbed netlist to {new_path}: {e}")
        return None

# --- Standalone Test Block ---
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 perturb.py <input.v> <output.v>")
        print("Example: python3 perturb.py design.v test_perturb.v")
        sys.exit(1)

    in_file = sys.argv[1]
    out_file = sys.argv[2]

    if not os.path.exists(in_file):
        print(f"[ERROR] Input file not found: {in_file}")
        sys.exit(1)

    print(f"--- Running Perturbation Test ---")
    print(f"Input:  {in_file}")
    print(f"Output: {out_file}")
    print(f"Configuration:")
    print(f"  Max Gates to Modify: {MAX_GATES_TO_MODIFY_PER_RUN}")
    print(f"  Prob Apply Change:   {PROB_APPLY_SIZE_CHANGE}")
    # print(f"  Target Sizes Per Cell: {SIZING_TARGETS_PER_CELL}") # Can be very long
    print(f"  Sizable Cell Bases ({len(SIZABLE_CELL_BASES)} types): {list(SIZABLE_CELL_BASES)[:5]}...") # Show first 5
    print(f"  Compiled Regex Patterns for sizes: {list(REGEX_PATTERNS.keys())}")
    print(f"  Assumed Cell Suffix: '{CELL_SUFFIX}'")


    # Run perturbation
    result_path = perturb_netlist(in_file, out_file)

    if result_path:
        print(f"[OK] Perturbation function finished.")
        print(f"--- Running diff to check for changes (output indicates differences) ---")
        diff_command = f"diff -u {in_file} {out_file}"
        print(f"Executing: {diff_command}")

        diff_process = os.popen(diff_command)
        diff_output = diff_process.read()
        exit_code = diff_process.close()

        print(f"--- Diff output ---")
        print(diff_output if diff_output else "<No differences found>")
        print(f"--- End Diff output ---")
        print(f"Diff exit code: {exit_code}")

        if exit_code is None:
            print("[WARNING] diff reported no differences. Perturbation might have had no effect this run.")
            print("          This can happen due to randomness or low limit/probability.")
        elif exit_code == 1*256 or exit_code == 1 :
             print("[INFO] diff reported differences as expected.")
        elif exit_code is not None:
             print(f"[WARNING] diff command exited with unexpected status {exit_code}. Check diff output.")
             if diff_output:
                  print("[INFO] Differences were found in the output despite the unusual exit code.")
             else:
                  print("[ERROR] No differences found in output and diff had unusual exit code.")

    else:
        print(f"[FAIL] Perturbation failed for {in_file}")
        sys.exit(1)