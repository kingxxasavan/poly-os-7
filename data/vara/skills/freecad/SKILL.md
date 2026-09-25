---
name: freecad
description: Script solid (CAD) parts with FreeCAD's Python API and export STEP or STL
---

# FreeCAD from scripts

Run scripts with `freecadcmd` through run_command (write the script to a .py file first):
`freecadcmd -c "exec(open('/path/part.py').read())"`.

```python
import FreeCAD as App, Part, Mesh
doc = App.newDocument("Part")
base = Part.makeBox(40, 25, 4)                                  # mm
post = Part.makeCylinder(5, 30, App.Vector(20, 12.5, 4))
hole = Part.makeCylinder(2.25, 40, App.Vector(20, 12.5, -1))
shape = base.fuse(post).cut(hole).removeSplitter()
Part.show(shape)
shape.exportStep("/path/part.step")                             # for CAD and CNC
mesh = Mesh.Mesh(shape.tessellate(0.05)); mesh.write("/path/part.stl")   # for printing
doc.saveAs("/path/part.FCStd")
print(shape.BoundBox)
```

- STEP keeps exact geometry (share with other CAD tools); STL is for slicers. Check STLs with `model_info`.
- Round edges with `shape.makeFillet(radius, edges)`, choosing edges by position (`e.BoundBox`); fillets
  fail when the radius is bigger than the faces next to the edge, so start small.
