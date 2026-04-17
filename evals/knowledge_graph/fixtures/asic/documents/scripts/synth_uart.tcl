###############################################################################
# synth_uart.tcl
# Synopsys Design Compiler synthesis script for the UART subsystem
#
# Target library : TSMC 28nm HPC+ (sc9mc_cln28hpc_base_rvt_ss_typical_max_0p81v_125c)
# Tool           : Synopsys Design Compiler R-2023.12
# Top module     : uart
# Dependencies   : uart_tx.sv, uart_rx.sv, prim_fifo_sync.sv, prim_flop_2sync.sv
###############################################################################

##
## 1. Setup environment
##
set DESIGN_NAME  "uart"
set TARGET_LIB   "sc9mc_cln28hpc_base_rvt_ss_typical_max_0p81v_125c.db"
set LINK_LIB     [list "*" ${TARGET_LIB}]
set SRC_DIR      "../rtl"
set RESULTS_DIR  "./results"

file mkdir ${RESULTS_DIR}

set_app_var target_library ${TARGET_LIB}
set_app_var link_library    ${LINK_LIB}
set_app_var symbol_library  "generic.sdb"

##
## 2. Read RTL sources
##
puts "INFO: Reading RTL sources..."

read_sverilog -sv09 [list \
    ${SRC_DIR}/prim_flop_2sync.sv  \
    ${SRC_DIR}/prim_fifo_sync.sv   \
    ${SRC_DIR}/uart_tx.sv          \
    ${SRC_DIR}/uart_rx.sv          \
    ${SRC_DIR}/uart_reg_top.sv     \
    ${SRC_DIR}/uart.sv             \
]

current_design ${DESIGN_NAME}
link

##
## 3. Apply timing constraints
##
puts "INFO: Applying constraints..."

# Primary clock: clk_i at 50 MHz (20 ns period)
create_clock -name "clk_i" -period 20.0 [get_ports clk_i]
set_clock_uncertainty -setup 0.3 [get_clocks clk_i]
set_clock_uncertainty -hold  0.1 [get_clocks clk_i]
set_clock_transition 0.15 [get_clocks clk_i]

# Input / output delays (APB interface)
set_input_delay  -max 3.0 -clock clk_i [get_ports {psel_i penable_i pwrite_i paddr_i pwdata_i}]
set_output_delay -max 2.0 -clock clk_i [get_ports {prdata_o pready_o}]

# False path on asynchronous reset synchronizer
set_false_path -from [get_ports rst_ni]

# Drive strength assumption for inputs
set_driving_cell -lib_cell BUF_X4 -library ${TARGET_LIB} [all_inputs]
set_load 0.05 [all_outputs]

##
## 4. Area constraints
##
# Allow DC to trade off timing slack for area after meeting timing
set_max_area 0

##
## 5. Compile
##
puts "INFO: Running compile_ultra..."
compile_ultra -timing_high_effort_script -no_autoungroup

##
## 6. Reports
##
puts "INFO: Writing reports..."
report_timing  -max_paths 20 -path full -delay max > ${RESULTS_DIR}/${DESIGN_NAME}_timing.rpt
report_area                                        > ${RESULTS_DIR}/${DESIGN_NAME}_area.rpt
report_power   -analysis_effort high               > ${RESULTS_DIR}/${DESIGN_NAME}_power.rpt
report_constraint -all_violators                   > ${RESULTS_DIR}/${DESIGN_NAME}_violations.rpt

##
## 7. Write netlists and constraints
##
write -format verilog -hierarchy -output ${RESULTS_DIR}/${DESIGN_NAME}_netlist.v
write_sdc ${RESULTS_DIR}/${DESIGN_NAME}.sdc

puts "INFO: Synthesis complete for ${DESIGN_NAME}."
