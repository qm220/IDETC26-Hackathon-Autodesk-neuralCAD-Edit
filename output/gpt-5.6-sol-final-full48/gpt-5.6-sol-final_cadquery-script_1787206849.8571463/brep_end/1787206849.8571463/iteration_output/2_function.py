def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    if not original.isValid():
        raise RuntimeError("The imported STEP shape is invalid")

    bbox = original.BoundingBox()

    # The enlarged rear body occupies x <= 100 mm. Its lower Z-side already
    # contains the requested R30 and R5 rounds, while the corresponding upper
    # Z-side edges are sharp. Reconstruct the upper half of only this enlarged
    # body by reflecting its existing lower half about the thickness mid-plane.
    # This copies the existing radii and their corner transitions exactly.
    x_split = 100.0
    z_mid = 0.5 * (bbox.zmin + bbox.zmax)
    margin = max(10.0, 0.05 * max(bbox.xlen, bbox.ylen, bbox.zlen))

    region_x0 = bbox.xmin - margin
    region_y0 = bbox.ymin - margin
    region_dx = x_split - region_x0
    region_dy = bbox.ylen + 2.0 * margin

    lower_box = cq.Solid.makeBox(
        region_dx,
        region_dy,
        z_mid - (bbox.zmin - margin),
        cq.Vector(region_x0, region_y0, bbox.zmin - margin)
    )

    upper_box = cq.Solid.makeBox(
        region_dx,
        region_dy,
        (bbox.zmax + margin) - z_mid,
        cq.Vector(region_x0, region_y0, z_mid)
    )

    # Capture the already-correct rounded half before modifying the body.
    rounded_lower_reference = original.intersect(lower_box)
    if rounded_lower_reference.Volume() <= 0.0:
        raise RuntimeError("Could not isolate the rounded reference half")

    # Reflect across the global XY plane translated to z=z_mid.
    transform = gp_Trsf()
    transform.SetMirror(
        gp_Ax2(gp_Pnt(0.0, 0.0, z_mid), gp_Dir(0.0, 0.0, 1.0))
    )
    transformed = BRepBuilderAPI_Transform(
        rounded_lower_reference.wrapped, transform, True
    )
    transformed.Build()
    if not transformed.IsDone():
        raise RuntimeError("Could not mirror the existing rounded geometry")

    rounded_upper_patch = cq.Shape.cast(transformed.Shape())

    # Remove only the sharp upper half of the enlarged body. The shank,
    # circular bore, rectangular pocket, and all existing lower rounds remain
    # directly inherited from the original model.
    preserved_geometry = original.cut(upper_box)
    result_shape = preserved_geometry.fuse(rounded_upper_patch).clean()

    if not result_shape.isValid():
        raise RuntimeError("The reconstructed model is not a valid shape")

    solids = result_shape.Solids()
    if len(solids) != 1:
        raise RuntimeError(
            "Expected one connected solid after reconstruction, found %d" % len(solids)
        )

    result_bbox = result_shape.BoundingBox()
    bbox_tol = 1.0e-4
    bbox_values_original = (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax
    )
    bbox_values_result = (
        result_bbox.xmin, result_bbox.xmax,
        result_bbox.ymin, result_bbox.ymax,
        result_bbox.zmin, result_bbox.zmax
    )
    if any(abs(a - b) > bbox_tol for a, b in zip(bbox_values_original, bbox_values_result)):
        raise RuntimeError("The operation unexpectedly changed the overall envelope")

    print("Mirrored rounded enlarged-body half about z =", z_mid)
    print("VALID", result_shape.isValid())
    print("SOLIDS", len(solids))
    print("VOLUME original/result", original.Volume(), result_shape.Volume())
    print("BBOX", *bbox_values_result)
    print(
        "COUNTS faces edges vertices",
        len(result_shape.Faces()),
        len(result_shape.Edges()),
        len(result_shape.Vertices())
    )

    return cq.Workplane(obj=result_shape)
