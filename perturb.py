import random
import re
import sys
import time
import os # For diff command in test

# --- Configuration ---

# Maximum number of gates to modify in a single call to perturb_netlist
MAX_GATES_TO_MODIFY_PER_RUN = 5 # <<< ADJUST THIS VALUE AS NEEDED (e.g., 1, 3, 5, 10)

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
PROB_APPLY_SIZE_CHANGE = 0.8 # High chance to apply change once identified & within limit

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


# --- Perturbation Function ---
def perturb_netlist(verilog_path, new_path):
    try:
        with open(verilog_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"[ERROR] Input netlist not found: {verilog_path}")
        return None

    perturbed_lines = []
    gates_sized_count = 0
    buffer_inserted = False
    gates_modified_this_run = 0 # Counter for this specific run

    # --- Create a list of potential modification points ---
    potential_mods = [] # Store tuples: (line_index, current_size, match_object)
    for line_num, line in enumerate(lines):
        for current_size, pattern in REGEX_PATTERNS.items():
            match = pattern.search(line)
            if match:
                cell_name_base = match.group(1)
                cell_suffix_matched = match.group(2)
                full_base = cell_name_base + cell_suffix_matched
                if full_base in SIZABLE_CELL_BASES:
                    # Check if this size can actually be changed
                    targets_for_this_cell = SIZING_TARGETS_PER_CELL.get(full_base)
                    if targets_for_this_cell:
                        possible_new_sizes = targets_for_this_cell.get(current_size)
                        if possible_new_sizes: # Ensure there are targets
                            potential_mods.append((line_num, current_size, match))
                            break # Found a sizable gate on this line, move to next line

    # --- Randomly select modifications up to the limit ---
    random.shuffle(potential_mods)
    lines_to_modify_indices = set() # Keep track of lines already modified

    for line_index, current_size, match in potential_mods:
        if gates_modified_this_run >= MAX_GATES_TO_MODIFY_PER_RUN:
            break # Stop if we hit the limit

        # Check if this line was already modified by a previous random choice
        if line_index in lines_to_modify_indices:
            continue

        # Apply the change based on probability
        if random.random() < PROB_APPLY_SIZE_CHANGE:
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
                     new_size = random.choice(possible_new_sizes)
                     original_line = lines[line_index] # Get the original line content

                     # Perform replacement
                     modified_line = match.re.sub( # Use match.re to get the compiled pattern
                         f"{cell_name_base}{cell_suffix_matched}{new_size}{whitespace_after_size}{instance_name}{space_and_paren}",
                         original_line,
                         count=1
                     )

                     if modified_line != original_line:
                         lines[line_index] = modified_line # Modify the line in the list
                         gates_sized_count += 1
                         gates_modified_this_run += 1
                         lines_to_modify_indices.add(line_index) # Mark line as modified

    # --- Buffer Insertion (Still Disabled) ---
    # The loop structure changed, so this part would need adjustment if re-enabled
    # It's better placed *after* gate sizing potentially modifies the 'lines' list.
    final_lines = []
    for line in lines:
        # if "endmodule" in line and random.random() < 0.0:
        #    ... (buffer insertion code) ...
        final_lines.append(line)
    # perturbed_lines = final_lines # Assign if buffer insertion is active


    # Use the potentially modified 'lines' list directly
    perturbed_lines = lines

    try:
        with open(new_path, 'w') as f:
            f.writelines(perturbed_lines)
        print(f"  [Perturb OK] Saved to {new_path}. Gates sized: {gates_sized_count} (Limit: {MAX_GATES_TO_MODIFY_PER_RUN}). Buffer inserted: {buffer_inserted} (Disabled)")
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