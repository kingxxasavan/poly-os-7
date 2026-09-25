---
name: blender
description: Build, change, import/export or render 3D scenes with Blender's Python API (bpy), without opening its window
---

# Blender from scripts

Use the `blender` tool. The script runs in `blender --background`, so there is no viewport, no
selection by clicking and no UI context: prefer the `bpy.data` API over `bpy.ops` where you can.

## Start clean, work in millimeters

```python
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)   # empty scene (skip when editing a .blend)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 0.001            # 1 unit = 1 mm, good for 3D printing
scene.unit_settings.length_unit = 'MILLIMETERS'
```

## Make and change objects

```python
bpy.ops.mesh.primitive_cube_add(size=20, location=(0, 0, 10))
cube = bpy.context.active_object
cube.name = "Base"
bevel = cube.modifiers.new("Bevel", 'BEVEL'); bevel.width = 1.5; bevel.segments = 3
bpy.ops.mesh.primitive_cylinder_add(radius=4, depth=30, location=(0, 0, 10))
hole = bpy.context.active_object
cut = cube.modifiers.new("Hole", 'BOOLEAN'); cut.operation = 'DIFFERENCE'; cut.object = hole
hole.hide_render = True; hole.hide_viewport = True
```

Apply modifiers before exporting for printing: `bpy.context.view_layer.objects.active = cube;
bpy.ops.object.modifier_apply(modifier="Hole")`, then remove the cutter with `bpy.data.objects.remove(hole)`.

## Import and export

- STL: `bpy.ops.wm.stl_import(filepath=...)` and `bpy.ops.wm.stl_export(filepath=..., export_selected_objects=True)` (Blender 4.2+);
  older versions use `bpy.ops.import_mesh.stl` / `bpy.ops.export_mesh.stl`.
- OBJ: `bpy.ops.wm.obj_import` / `bpy.ops.wm.obj_export`. glTF: `bpy.ops.export_scene.gltf(filepath="x.glb")`.
- Check the Blender version first when unsure: `print(bpy.app.version_string)`.

## Render a preview image

```python
cam_data = bpy.data.cameras.new("Cam"); cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam); scene.camera = cam
cam.location = (60, -60, 50); cam.rotation_euler = (1.05, 0, 0.785)
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN')); scene.collection.objects.link(sun)
scene.render.engine = 'BLENDER_EEVEE_NEXT'   # 'BLENDER_EEVEE' before 4.2; 'CYCLES' with scene.cycles.device = 'CPU'
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.filepath = "/path/to/preview.png"
bpy.ops.render.render(write_still=True)
```

EEVEE needs a GPU with OpenGL; if it fails in the background, use Cycles on the CPU with
`scene.cycles.samples = 32`.

## Finish

- Save: `bpy.ops.wm.save_as_mainfile(filepath="/path/model.blend")`.
- `print()` sizes and names you need (`obj.dimensions`), and check exported STLs with `model_info`.
- Offer to open the result: the `open` tool with the .blend file opens Blender.
