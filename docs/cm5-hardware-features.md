# CM5 and iTuner carrier-board features

Recorded on 18 November 2026. The system consists of the Raspberry Pi CM5 computer module, the custom iTuner carrier board, and a separate encoder board.

## CM5 computer module

1. **Processor:** Four ARM Cortex-A76 cores running at 2.4 GHz.
2. **RAM:** The installed module has **2 GB**, shared by Linux, the application and graphics.
3. **Storage:** The installed **CM5 Lite** has no onboard eMMC. This system currently boots from microSD.
4. **Graphics:** VideoCore VII GPU, providing hardware acceleration for the interface, spectrum and waterfall.
5. **Video:** The module supports two HDMI outputs up to 4K60 and two MIPI camera/display interfaces. Availability on the finished device depends on carrier wiring; this does not establish that the carrier has HDMI sockets.
6. **Connectivity:** Gigabit Ethernet, two USB 3 interfaces and one USB 2 interface.
7. **Expansion:** A PCIe interface for devices such as an NVMe SSD.
8. **Hardware control:** GPIO, I²C, SPI, UART, PWM and I²S for controls, audio and peripherals.
9. **Wireless options:** CM5 variants can include dual-band Wi-Fi and Bluetooth 5. Wireless hardware on this particular module has not been confirmed.

Module specifications: [Raspberry Pi CM5](https://www.raspberrypi.com/products/compute-module-5/).

## Custom iTuner carrier board

These features are based on the August 2026 schematic and project hardware documentation. Connector provision does not establish that every feature has been tested.

1. **CM5 mounting connectors:** Connect the module to carrier power and peripherals.
2. **MicroSD slot:** Provides removable operating-system and application storage for the Lite module.
3. **Gigabit Ethernet socket:** Wired network access for remote SDR receivers and administration.
4. **USB 3 connectivity:** A stacked pair of USB 3 sockets is shown in the schematic.
5. **USB 2 expansion:** A four-port USB 2 hub feeds four internal peripheral connectors.
6. **USB power selection:** GPIO42 selects between USB 2 and USB 3 power groups. They are not independently powered together in the existing configuration.
7. **USB-C connection:** Includes USB 2 routing and boot/programming support.
8. **M.2 SSD slot:** An M-key PCIe connection with mounting positions for 2230, 2242, 2260 and 2280 SSDs. SSD operation has not been confirmed here.
9. **Touchscreen interface:** The working display is an **800 × 1280 panel**, used in **1280 × 800 landscape**, connected through four-lane MIPI DSI.
10. **Capacitive touch:** A **GT911 controller** provides touchscreen input over I²C.
11. **Backlight driver:** Powers the LCD backlight. On the tested board its enable is tied high, so software brightness control is not currently wired.
12. **Audio codec:** An **ES8316** handles digital-to-analog audio; the application uses stereo 48 kHz output.
13. **Speaker amplifier:** A **TPA3113 Class-D amplifier** drives the speaker output.
14. **Headphone output:** Includes jack detection so inserting headphones can automatically mute the speaker.
15. **Physical controls:** A separate encoder board connects through a 20-pin ribbon and provides **TUNE, VIEW and NAV**, with push actions on VIEW and NAV. This describes the design; full encoder operation remains unconfirmed.
16. **Additional buttons:** An **MCP23008 I/O expander** supports signals labelled MODE, BAND, DISP, MAP and PTT.
17. **Cooling connection:** A fan connector provides PWM speed control and tachometer feedback.
18. **Clock backup:** An RTC battery connector supports keeping time while main power is off.
19. **Service controls:** Boot/power controls and status LEDs assist startup and maintenance.

The carrier provides the computer, display, audio and control platform. RF reception comes from a connected USB receiver or a network SDR.

## Evidence and references

- Installed module identification and storage were checked during CM5 SSH diagnostics preceding this inventory: Raspberry Pi Compute Module 5 Lite Rev 1.0, 2 GB RAM, microSD root filesystem.
- [Display reference](../hardware/cm5/reference-display/README.md)
- [Audio configuration](cm5-audio.md) and [audio hardware notes](../hardware/cm5/audio/README.md)
- [Encoder hardware notes](../hardware/cm5/encoders/README.md)
- [ADS-B and USB configuration](adsb.md)
- Carrier schematic: `SCH_CM5_MAIN_2026-08-26.pdf`, under the local design archive `/Users/lucaiuli/Downloads/raspipcb-ituner1-cm5_sdr/main-board/exported-schematics/`.

This is a dated inventory, not a claim that all schematic features are populated, enabled or verified on the current physical unit. Recheck hardware and runtime state when those distinctions matter.
