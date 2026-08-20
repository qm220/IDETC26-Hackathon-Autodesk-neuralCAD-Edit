def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.gp import gp_GTrsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported

    solids = source.Solids()
    if len(solids) != 1:
        raise ValueError(f"Expected one frame solid, found {len(solids)}")
    frame = solids[0]

    # Use the largest planar seating face to determine the frame plane.
    planar_faces = [f for f in frame.Faces() if f.geomType() == "PLANE"]
    if not planar_faces:
        raise ValueError("The input frame has no planar face from which to determine orientation")

    seating_face = max(planar_faces, key=lambda f: f.Area())
    normal = seating_face.normalAt(seating_face.Center()).normalized()
    if normal.z < 0.0:
        normal = -normal

    # The long frame direction is global X in the supplied model. The height
    # direction lies in the seating-face plane and is perpendicular to X.
    width_axis = cq.Vector(1.0, 0.0, 0.0)
    height_axis = normal.cross(width_axis).normalized()
    if height_axis.z < 0.0:
        height_axis = -height_axis

    def projection(point, axis):
        return point.x * axis.x + point.y * axis.y + point.z * axis.z

    vertices = frame.Vertices()
    x_values = [projection(v.Center(), width_axis) for v in vertices]
    y_values = [projection(v.Center(), height_axis) for v in vertices]
    z_values = [projection(v.Center(), normal) for v in vertices]

    xmin, xmax = min(x_values), max(x_values)
    ymin, ymax = min(y_values), max(y_values)
    zmin, zmax = min(z_values), max(z_values)

    original_height = ymax - ymin
    height_increase = 5.0  # 0.5 cm in millimetres

    # Insert the extra length through a central band of the straight side rails.
    # This preserves the complete top and bottom rails, corner radii, fillets,
    # wall thickness, and the rail cross-sectional area profile.
    center_y = 0.5 * (ymin + ymax)
    stretch_band = min(40.0, original_height * 0.20)
    if stretch_band <= 0.0:
        raise ValueError("Could not determine a positive frame stretch band")

    band_low = center_y - 0.5 * stretch_band
    band_high = center_y + 0.5 * stretch_band
    margin = max(100.0, original_height)

    def affine_transform(shape, matrix, translation=(0.0, 0.0, 0.0)):
        transform = gp_GTrsf()
        for row in range(3):
            for col in range(3):
                transform.SetValue(row + 1, col + 1, float(matrix[row][col]))
            transform.SetValue(row + 1, 4, float(translation[row]))
        transformed = BRepBuilderAPI_GTransform(
            shape.wrapped, transform, True
        ).Shape()
        return cq.Shape.cast(transformed)

    # Matrix mapping local coordinates (width, height, profile-normal) into the
    # original model's global coordinate system.
    basis_matrix = [
        [width_axis.x, height_axis.x, normal.x],
        [width_axis.y, height_axis.y, normal.y],
        [width_axis.z, height_axis.z, normal.z],
    ]

    def oriented_box(local_y0, local_y1):
        local_box = cq.Solid.makeBox(
            (xmax - xmin) + 2.0 * margin,
            local_y1 - local_y0,
            (zmax - zmin) + 2.0 * margin,
            cq.Vector(xmin - margin, local_y0, zmin - margin),
        )
        return affine_transform(local_box, basis_matrix)

    lower_box = oriented_box(ymin - margin, band_low)
    middle_box = oriented_box(band_low, band_high)
    upper_box = oriented_box(band_high, ymax + margin)

    lower = frame.intersect(lower_box)
    middle = frame.intersect(middle_box)
    upper = frame.intersect(upper_box)

    # Scale only in the frame-height direction, fixing the lower boundary of the
    # middle band. The side-rail cross section is therefore unchanged.
    scale = (stretch_band + height_increase) / stretch_band
    k = scale - 1.0
    h = height_axis
    stretch_matrix = [
        [1.0 + k * h.x * h.x, k * h.x * h.y, k * h.x * h.z],
        [k * h.y * h.x, 1.0 + k * h.y * h.y, k * h.y * h.z],
        [k * h.z * h.x, k * h.z * h.y, 1.0 + k * h.z * h.z],
    ]
    stretch_translation = (
        -k * band_low * h.x,
        -k * band_low * h.y,
        -k * band_low * h.z,
    )

    middle_extended = affine_transform(
        middle, stretch_matrix, stretch_translation
    )
    upper_shifted = upper.translate(height_axis.multiply(height_increase))

    # Shape.fuse may return a Compound even when its contents form one solid.
    # Do not call Workplane.removeSplitter() on that Shape; instead fuse and
    # return the valid resulting shape directly.
    result = lower.fuse(middle_extended).fuse(upper_shifted)

    result_solids = result.Solids()
    if len(result_solids) != 1:
        raise ValueError(
            f"Height edit produced {len(result_solids)} solids instead of one"
        )

    final_shape = result_solids[0]
    final_y = [projection(v.Center(), height_axis) for v in final_shape.Vertices()]
    final_height = max(final_y) - min(final_y)
    measured_increase = final_height - original_height

    print(f"Input valid: {frame.isValid()}")
    print(f"Original frame height: {original_height:.6f} mm")
    print(f"Requested increase: {height_increase:.6f} mm")
    print(f"Final frame height: {final_height:.6f} mm")
    print(f"Measured increase: {measured_increase:.6f} mm")
    print(f"Output valid: {final_shape.isValid()}")
    print(f"Output solids: {len(final_shape.Solids())}")

    if abs(measured_increase - height_increase) > 1.0e-4:
        raise ValueError(
            f"Measured height increase {measured_increase:.6f} mm does not match 5 mm"
        )
    if not final_shape.isValid():
        raise ValueError("The edited frame is not a valid B-rep")

    return cq.Workplane("XY").newObject([final_shape])