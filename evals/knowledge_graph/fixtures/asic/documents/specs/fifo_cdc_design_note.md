# Design Note: FIFO and Clock Domain Crossing Strategy

**Document ID:** DN-CDC-003  
**Version:** 1.1  
**Status:** Approved  
**Owner:** Physical Design / CDC Team  
**Date:** 2024-09-30  

---

## 1. Background

This design note documents the synchronization strategy used when `prim_fifo_sync` instances
are placed across clock domain boundaries in the Earl Grey SoC. While `prim_fifo_sync` is a
purely synchronous FIFO (all ports share a single clock), write and read interfaces often
originate in different clock domains. This note describes the handshake and gray-code
mechanisms layered on top of `prim_fifo_sync` to achieve safe CDC.

---

## 2. Modules Referenced

| Module              | Role                                                      |
|---------------------|-----------------------------------------------------------|
| `prim_fifo_sync`    | Synchronous FIFO primitive; depth is parameterized        |
| `prim_pulse_sync`   | Single-pulse synchronizer using a toggle-and-detect scheme|

`prim_fifo_sync` accepts a `Depth` parameter which **must be a power of 2** to ensure
correct gray-code pointer arithmetic. Non-power-of-2 depths cause pointer aliasing and will
result in data corruption. Allowed values: 4, 8, 16, 32, 64.

---

## 3. Clock Domains

Two clock domains are relevant to the FIFO CDC interface:

| Domain Label | Signal   | Nominal Frequency | Source                    |
|--------------|----------|-------------------|---------------------------|
| Source domain| `clk_src` | 96 MHz           | USB PLL output            |
| Destination  | `clk_dst` | 48 MHz           | Divided-down system clock |

The source domain (USB) pushes data into the FIFO write port. The destination domain
(system bus) reads from the FIFO read port. Because write rate can exceed read rate, the
FIFO must be sized to absorb burst traffic without overflow. The recommended minimum depth
for this configuration is 16 entries.

---

## 4. Synchronization Strategy

### 4.1 Two-Flop Synchronizer

All control signals crossing from `clk_src` to `clk_dst` (or vice versa) are passed through
a two-flop synchronizer implemented in `prim_flop_2sync`. This provides:

- Mean time between failures (MTBF) > 10^9 years at the design's metastability window
- Two-cycle latency in the destination domain

`prim_pulse_sync` wraps `prim_flop_2sync` with toggle-and-detect logic so that a single
source-domain pulse maps reliably to a single destination-domain pulse, regardless of the
clock ratio.

### 4.2 Gray-Code Pointer Synchronization

FIFO full and empty status signals are derived from write and read pointers that are
synchronized across clock domains using gray-code encoding:

1. Write pointer (`wptr`) is encoded to gray code in `clk_src`.
2. Gray-coded `wptr` is synchronized into `clk_dst` via two-flop chain.
3. `prim_fifo_sync` computes the "full" condition against the synchronized gray pointer.

This guarantees that at most one bit changes per clock cycle during synchronization,
eliminating multi-bit metastability in pointer comparisons.

---

## 5. CDC Verification

CDC closure is verified with **Jaspergold CDC App** (Cadence, version 2023.09). The
verification plan requires:

- All `prim_pulse_sync` instances passing the reconvergence check
- All gray-code pointer paths passing the multi-bit stability rule
- No unresolved asynchronous resets crossing domain boundaries

The Jaspergold script `jg_cdc_uart.tcl` lists all CDC path exceptions and must be updated
whenever a new `prim_fifo_sync` instance is added at a domain boundary.

---

## 6. Depth Parameter Constraint Summary

| Constraint              | Rule                                      |
|-------------------------|-------------------------------------------|
| Depth must be power of 2 | Gray-code arithmetic correctness         |
| Minimum depth (USB CDC) | 16 entries (burst absorption requirement) |
| Maximum depth (area)    | 64 entries (area budget constraint)       |
| Default depth           | 16 entries                                |

Violations of the power-of-2 constraint will be caught by an `initial` block assertion in
`prim_fifo_sync`:

```systemverilog
initial begin
  assert ((Depth & (Depth - 1)) == 0)
    else $fatal(1, "prim_fifo_sync: Depth must be a power of 2");
end
```

---

## 7. Revision History

| Version | Date       | Author     | Change                                   |
|---------|------------|------------|------------------------------------------|
| 1.0     | 2024-07-15 | T. Watkins | Initial release                          |
| 1.1     | 2024-09-30 | T. Watkins | Added Jaspergold verification section    |
