# UART Subsystem Design Specification

**Document ID:** SPEC-UART-001  
**Version:** 1.3  
**Status:** Released  
**Owner:** Digital Design Team  
**Date:** 2024-11-12  

---

## 1. Overview

This document specifies the design requirements and microarchitecture for the UART subsystem
integrated into the OpenTitan Earl Grey SoC. The subsystem consists of two primary RTL modules:
`uart_tx` (transmit path) and `uart_rx` (receive path), both of which share a common register
interface and baud rate generator.

The subsystem is intended for low-speed serial communication with external peripherals using the
AMBA APB protocol for register access and operates from a single clock domain driven by `clk_i`.

---

## 2. Requirements

| ID             | Requirement                                                              | Priority |
|----------------|--------------------------------------------------------------------------|----------|
| REQ-UART-001   | Must support 8N1 format (8 data bits, no parity, 1 stop bit)            | MUST     |
| REQ-UART-002   | Default baud rate shall be 115200 bps                                    | MUST     |
| REQ-UART-003   | Baud rate shall be runtime-programmable via NCO register                 | MUST     |
| REQ-UART-004   | TX and RX FIFOs shall each be 32 entries deep (prim_fifo_sync)          | MUST     |
| REQ-UART-005   | The module shall assert an interrupt on TX FIFO empty and RX FIFO full  | SHOULD   |
| REQ-UART-006   | Parity mode (even/odd/none) shall be software-selectable                | SHOULD   |
| REQ-UART-007   | Must tolerate up to ±2% baud rate deviation on RX                       | MUST     |

---

## 3. Signal Interface

### 3.1 Clock and Reset

| Signal    | Direction | Width | Description                         |
|-----------|-----------|-------|-------------------------------------|
| `clk_i`   | input     | 1     | System clock, 50 MHz nominal        |
| `rst_ni`  | input     | 1     | Active-low asynchronous reset       |

### 3.2 APB Register Interface

The `uart_tx` and `uart_rx` control registers are exposed via an AMBA APB slave port. The APB
address map starts at offset `0x0` relative to the IP base address. Register access width is 32
bits; byte enables are not required.

| Signal        | Direction | Width | Description              |
|---------------|-----------|-------|--------------------------|
| `psel_i`      | input     | 1     | APB peripheral select    |
| `penable_i`   | input     | 1     | APB enable               |
| `pwrite_i`    | input     | 1     | APB write enable         |
| `paddr_i`     | input     | 12    | APB address              |
| `pwdata_i`    | input     | 32    | APB write data           |
| `prdata_o`    | output    | 32    | APB read data            |
| `pready_o`    | output    | 1     | APB ready                |

---

## 4. TX Finite State Machine

The `uart_tx` module implements a Mealy FSM with the following states:

| State      | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `IDLE`     | No active transmission. Module de-asserts `tx_o` high (mark state).    |
| `START`    | Assert `tx_o` low for one baud period to signal start of frame.         |
| `DATA`     | Shift out 8 data bits LSB-first, one bit per baud period.               |
| `PARITY`   | Optionally transmit parity bit; skipped when parity mode is NONE.       |
| `STOP`     | Assert `tx_o` high for one or two baud periods per `CTRL.nstop` setting.|

State transition from `IDLE` to `START` occurs when the TX FIFO becomes non-empty and the baud
rate generator produces a `tick` pulse. The FSM re-enters `IDLE` after `STOP` completes and the
FIFO is empty; otherwise it re-enters `START` immediately for back-to-back frames.

---

## 5. Baud Rate Generator

The baud rate generator uses a 16-bit numerically-controlled oscillator (NCO). The tick period
is:

```
tick_period = clk_i_freq / baud_rate
```

For a 50 MHz system clock and 115200 baud:

```
NCO_INC = round((115200 / 50e6) * 2^16) = 0x0271
```

The NCO register `UART_CTRL.nco` is writable at runtime.

---

## 6. AXI-Lite Register Mirror (Optional)

An optional AXI-Lite register mirror may be instantiated for high-performance host interfaces.
When `AXI_LITE_EN` is set during synthesis, the module exposes an AXI4-Lite subordinate port
alongside the APB interface. The AXI-Lite port takes precedence for write ordering.

---

## 7. Timing Constraints

- **Clock:** `clk_i` at 50 MHz (20 ns period)
- **Setup margin target:** 200 ps after STA derating
- **Hold margin target:** 50 ps
- **Input delay (APB):** 3 ns max from clock edge
- **Output delay (APB):** 2 ns max before next clock edge
- **False path:** `rst_ni` synchronizer chain flagged as false path in constraints file

---

## 8. Synthesis Notes

Synthesis is performed with **Synopsys Design Compiler** (version R-2023.12) targeting the
TSMC 28nm HPC+ standard cell library. The synthesis script `synth_uart.tcl` sets the clock
constraint on `clk_i` and applies `compile_ultra` with timing-driven area optimization.

Estimated gate count: ~4,200 cells (NAND2 equivalent) excluding FIFOs.

---

## 9. Verification Plan

- RTL simulation: cocotb testbench targeting `uart_tx` and `uart_rx` in loopback
- Formal: bounded model check of TX FSM reachability (JasperGold)
- Lint: Verilator `--lint-only` pass required before tape-in
- Coverage: 100% toggle on primary I/O; 95% FSM state coverage target

---

## 10. Revision History

| Version | Date       | Author       | Change                                    |
|---------|------------|--------------|-------------------------------------------|
| 1.0     | 2024-08-01 | J. Alvarez   | Initial draft                             |
| 1.1     | 2024-09-14 | K. Patel     | Added AXI-Lite optional section           |
| 1.2     | 2024-10-05 | J. Alvarez   | Updated NCO formula and FIFO depth        |
| 1.3     | 2024-11-12 | K. Patel     | Released for tape-in review               |
