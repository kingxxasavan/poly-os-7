---
name: 3d-printing
description: Make parts printable (tolerances, walls, overhangs, orientation) and slice them to G-code with PrusaSlicer
---

# 3D printing

## Design rules for FDM printers (0.4 mm nozzle)

- Walls at least 1.2 mm (three lines); 2 mm or more for parts that take load.
- Holes print about 0.2 mm small: add 0.2–0.4 mm to diameters that must fit a screw or pin.
- Parts that fit together: 0.2 mm gap for a snug fit, 0.4 mm for a loose one.
- Overhangs up to 45° print without supports; chamfer instead of rounding downward-facing edges.
- Put the biggest flat face on the bed. Layer lines are the weak direction: orient so loads run along the layers.
- Check the size with `model_info` against the printer bed (ask the printer model, then `remember` it).

## Slice with PrusaSlicer (if installed)

```bash
prusa-slicer --export-gcode --layer-height 0.2 --fill-density 20% --support-material \
  --output parts/bracket.gcode parts/bracket.stl
```

- With the person's printer profile exported from PrusaSlicer (File > Export > Export Config): `--load myprinter.ini`.
- The G-code comment lines at the end report time and filament: `grep -E "estimated printing time|filament used" file.gcode`.
- Without PrusaSlicer, suggest PolyMarket, or give the STL to the person's slicer.

Never start a print on a networked printer (OctoPrint, Klipper/Moonraker) without the person's explicit yes.
