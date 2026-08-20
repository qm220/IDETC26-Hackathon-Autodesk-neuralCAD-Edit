def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    start_shape = model.val() if hasattr(model, "val") else model
    solids = list(start_shape.Solids())

    print("=== GROUNDED START-MODEL INSPECTION ===")
    print(f"valid={start_shape.isValid()}, solids={len(solids)}, faces={len(start_shape.Faces())}")
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: volume={solid.Volume():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    if len(solids) < 3:
        raise ValueError("Expected the two grounded blade solids and central retainer solid")

    # Grounded from the STEP inspection:
    # SOLID 0 is the oblique blade, SOLID 1 is the Z-directed blade, and
    # SOLID 2 is the central shaft/retaining-plate assembly.
    blade_oblique = solids[0]
    blade_vertical = solids[1]
    central_retainer = solids[2]

    for face_index in (14, 20, 33, 41, 42, 43, 89):
        face = start_shape.Faces()[face_index]
        c = face.Center()
        bb = face.BoundingBox()
        print(
            f"FACE {face_index}: type={face.geomType()}, area={face.Area():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    # FACE 33 and FACE 41 are the radius-6.35 mm longitudinal rounded walls
    # of the design selected for copying. Rotating the complete solid retains
    # that treatment on all four long blade boundaries, as well as its bores,
    # end geometry, and central transition design.
    third_blade_full = blade_vertical.rotate(
        cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), -60.0
    )

    target_thickness = 0.42
    stack_center_y = 6.35

    # Put the newly copied blade through the center plane of the stack. The two
    # original blades occupy adjacent layers. Small clearances keep the three
    # blade bodies topologically distinct while fitting well inside the
    # original 12.7 mm stack envelope.
    layer_gap = 0.08
    layer_pitch = target_thickness + layer_gap
    oblique_center_y = stack_center_y - layer_pitch
    new_center_y = stack_center_y
    vertical_center_y = stack_center_y + layer_pitch

    # The original localized transitions end at approximately radius 43.18 mm.
    # A radius-48 mm editing boundary therefore places the thickness step in
    # each blade's straight region while including the complete crossing and
    # shaft-clearance region.
    central_radius = 48.0
    join_overlap = 0.20
    axial_base_y = -50.0
    axial_height = 100.0
    central_cut_tool = cq.Solid.makeCylinder(
        central_radius,
        axial_height,
        cq.Vector(0, axial_base_y, 0),
        cq.Vector(0, 1, 0),
    )

    def thin_central_portion(full_blade, center_y, name):
        outer_portions = full_blade.cut(central_cut_tool)
        layer_tool = cq.Solid.makeCylinder(
            central_radius + join_overlap,
            target_thickness,
            cq.Vector(0, center_y - target_thickness / 2.0, 0),
            cq.Vector(0, 1, 0),
        )
        thin_center = full_blade.intersect(layer_tool)
        if not outer_portions.Solids():
            raise ValueError(f"Central cut removed all outer material from {name}")
        if not thin_center.Solids():
            raise ValueError(f"Failed to create the 0.42 mm center of {name}")
        edited = outer_portions.fuse(thin_center).clean()
        if not edited.isValid():
            raise ValueError(f"Invalid edited blade generated for {name}")
        bb = thin_center.BoundingBox()
        measured = bb.ymax - bb.ymin
        print(
            f"{name}: central layer y=({bb.ymin:.6f},{bb.ymax:.6f}), "
            f"measured thickness={measured:.6f} mm, solids={len(edited.Solids())}"
        )
        return edited

    edited_oblique = thin_central_portion(
        blade_oblique, oblique_center_y, "original oblique blade"
    )
    edited_vertical = thin_central_portion(
        blade_vertical, vertical_center_y, "original vertical blade"
    )
    edited_third = thin_central_portion(
        third_blade_full, new_center_y, "new third blade"
    )

    # Preserve separate assembly components rather than globally fusing blades,
    # shaft, and retaining plates.
    result_solids = []
    for component in (
        edited_oblique,
        edited_vertical,
        edited_third,
        central_retainer,
    ):
        result_solids.extend(component.Solids())

    result = cq.Compound.makeCompound(result_solids)
    print("=== RESULT INSPECTION ===")
    print(
        f"valid={result.isValid()}, solids={len(result.Solids())}, "
        f"faces={len(result.Faces())}, volume={result.Volume():.6f}"
    )
    for i, solid in enumerate(result.Solids()):
        bb = solid.BoundingBox()
        print(
            f"RESULT SOLID {i}: bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) "
            f"to ({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    return cq.Workplane("XY").newObject([result])