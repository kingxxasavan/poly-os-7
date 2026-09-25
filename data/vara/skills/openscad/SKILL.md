---
name: openscad
description: Design parametric, printable parts in OpenSCAD code and render them to STL, 3MF or a PNG preview
---

# OpenSCAD parts

OpenSCAD models are code, so they are easy to change later: put every size in a named variable
at the top. Units are millimeters.

## Write the model

```openscad
// Wall-mount bracket
width = 40; depth = 25; thickness = 4;
hole_d = 4.5;          // M4 screw, with clearance
$fn = 64;              // smooth circles

difference() {
    union() {
        cube([width, thickness, depth]);                 // back plate
        cube([width, depth, thickness]);                 // shelf
    }
    for (x = [10, width - 10])
        translate([x, -1, depth - 8]) rotate([-90, 0, 0]) cylinder(d = hole_d, h = thickness + 2);
}
```

Tips:
- Make cutting shapes 1 mm longer on both sides of what they cut (`-1` and `+2` above) so faces don't coincide.
- `hull()` makes rounded blocks; `minkowski()` is slow, avoid it for big parts.
- `linear_extrude()` of 2D shapes (`square`, `circle`, `polygon`, `text`) is fast and clean.
- If `BOSL2` is installed (`include <BOSL2/std.scad>`), it has threads, gears and rounded cubes.

## Render and check

1. `openscad` tool with `output: "parts/bracket.stl"` and the code. The code is saved next to it as `bracket.scad`.
2. Read the "Model size" line (or use `model_info`) and compare it with what was asked.
3. Render a preview with the same code and `output: "parts/bracket.png"`, and offer to open it.
4. Warnings like "Object may not be a valid 2-manifold" mean touching faces: overlap parts a little.

For printing, follow the 3d-printing skill too (tolerances, orientation, slicing).
