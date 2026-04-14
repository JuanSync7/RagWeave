"""
sim_gpio.py — cocotb testbench for the OpenTitan gpio module.

DUT       : gpio (hw/ip/gpio/rtl/gpio.sv)
Simulator : Verilator v5.018 (via cocotb-verilator backend)
Clock     : 100 MHz on clk_i (10 ns period)

Tests:
  - test_reg_read_write    : round-trip register access via TileLink BFM
  - test_rising_edge_intr  : rising-edge interrupt on GPIO[3]
  - test_level_high_intr   : level-high interrupt latch and W1C clear
  - test_glitch_filter     : confirm 16-cycle filter suppresses short pulses
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles
from cocotb.result import TestFailure

# Register offsets (byte addresses)
INTR_STATE          = 0x00
INTR_ENABLE         = 0x04
INTR_TEST           = 0x08
DATA_IN             = 0x10
DIRECT_OUT          = 0x14
DIRECT_OE           = 0x20
CTRL_EN_INPUT_FILTER = 0x38
INTR_CTRL_EN_RISING = 0x28
INTR_CTRL_EN_LVLHIGH = 0x30


async def reset_dut(dut, cycles=5):
    """Assert active-low reset for `cycles` clock cycles."""
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


async def tl_write(dut, addr, data):
    """Minimal TileLink-UL write via direct signal drive (single-beat, no error check)."""
    await RisingEdge(dut.clk_i)
    dut.tl_i_a_valid.value  = 1
    dut.tl_i_a_opcode.value = 0       # PutFullData
    dut.tl_i_a_address.value = addr
    dut.tl_i_a_data.value   = data
    dut.tl_i_a_mask.value   = 0xF
    await RisingEdge(dut.clk_i)
    while not dut.tl_o_a_ready.value:
        await RisingEdge(dut.clk_i)
    dut.tl_i_a_valid.value = 0
    # Wait for D-channel response
    while not dut.tl_o_d_valid.value:
        await RisingEdge(dut.clk_i)
    dut.tl_i_d_ready.value = 1
    await RisingEdge(dut.clk_i)
    dut.tl_i_d_ready.value = 0


async def tl_read(dut, addr) -> int:
    """Minimal TileLink-UL read; returns 32-bit read data."""
    await RisingEdge(dut.clk_i)
    dut.tl_i_a_valid.value  = 1
    dut.tl_i_a_opcode.value = 4       # Get
    dut.tl_i_a_address.value = addr
    dut.tl_i_a_mask.value   = 0xF
    await RisingEdge(dut.clk_i)
    while not dut.tl_o_a_ready.value:
        await RisingEdge(dut.clk_i)
    dut.tl_i_a_valid.value = 0
    while not dut.tl_o_d_valid.value:
        await RisingEdge(dut.clk_i)
    rdata = int(dut.tl_o_d_data.value)
    dut.tl_i_d_ready.value = 1
    await RisingEdge(dut.clk_i)
    dut.tl_i_d_ready.value = 0
    return rdata


@cocotb.test()
async def test_reg_read_write(dut):
    """Verify DIRECT_OUT and DIRECT_OE round-trip correctly."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())  # 100 MHz
    await reset_dut(dut)

    await tl_write(dut, DIRECT_OE,  0x0000_00FF)   # Enable output on pins [7:0]
    await tl_write(dut, DIRECT_OUT, 0x0000_00A5)   # Drive pattern 0xA5

    oe_readback  = await tl_read(dut, DIRECT_OE)
    out_readback = await tl_read(dut, DIRECT_OUT)

    assert oe_readback  == 0x0000_00FF, f"OE mismatch: {oe_readback:#010x}"
    assert out_readback == 0x0000_00A5, f"OUT mismatch: {out_readback:#010x}"
    dut._log.info("test_reg_read_write PASSED")


@cocotb.test()
async def test_rising_edge_intr(dut):
    """Assert GPIO[3] rising edge and confirm INTR_STATE[3] is set."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset_dut(dut)

    # Enable rising-edge interrupt on GPIO[3]
    await tl_write(dut, INTR_CTRL_EN_RISING, 1 << 3)
    await tl_write(dut, INTR_ENABLE,         1 << 3)

    # Drive GPIO[3] high
    dut.cio_gpio_i.value = 0x0000_0000
    await ClockCycles(dut.clk_i, 2)
    dut.cio_gpio_i.value = 0x0000_0008   # bit 3 = 1

    await ClockCycles(dut.clk_i, 3)
    intr_state = await tl_read(dut, INTR_STATE)
    assert intr_state & (1 << 3), f"Interrupt not set: {intr_state:#010x}"

    # Clear with W1C
    await tl_write(dut, INTR_STATE, 1 << 3)
    intr_state = await tl_read(dut, INTR_STATE)
    assert not (intr_state & (1 << 3)), "Interrupt did not clear after W1C"
    dut._log.info("test_rising_edge_intr PASSED")
