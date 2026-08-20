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

    # The broad seating face defines the normal of the frame's planar profile.
    planar_faces = [f for f in frame.Faces() if f.geomType() == "PLANE"]
    seating_face = max(planar_faces, key=lambda f: f.Area())
    n = seating_face.normalAt(seating_face.Center()).normalized()

    # Keep the normal directed generally toward global +Z for deterministic axes.
    if n.z < 0.0:
        n = -n

    # The frame width is parallel to global X. Its in-plane height direction is
    # perpendicular to both X and the seating-face normal.
    width_axis = cq.Vector(1.0, 0.0, 0.0)
    height_axis = n.cross(width_axis).normalized()
    if height_axis.z < 0.0:
        height_axis = -height_axis

    def projection(p, axis):
        return p.x * axis.x + p.y * axis.y + p.z * axis.z

    vertices = frame.Vertices()
    x_values = [projection(v.Center(), width_axis) for v in vertices]
    y_values = [projection(v.Center(), height_axis) for v in vertices]
    z_values = [projection(v.Center(), n) for v in vertices]

    ymin = min(y_values)
    ymax = max(y_values)
    original_height = ymax - ymin
    height_increase = 5.0  # 0.5 cm = 5 mm

    # Extend only the straight central portions of the two side rails. This moves
    # the complete upper half upward by 5 mm while preserving all rail sections,
    # corner radii, fillets, wall thicknesses, and seating-face profiles.
    center_y = 0.5 * (ymin + ymax)
    stretch_band = min(40.0, original_height * 0.20)
    band_low = center_y - 0.5 * stretch_band
    band_high = center_y + 0.5 * stretch_band

    margin = max(100.0, original_height)
    x0 = min(x_values) - margin
    x1 = max(x_values) + margin
    z0 = min(z_values) - margin
    z1 = max(z_values) + margin

    def affine_transform(shape, matrix, translation=(0.0, 0.0, 0.0)):
        trsf = gp_GTrsf()
        for row in range(3):
            for col in range(3):
                trsf.SetValue(row + 1, col + 1, float(matrix[row][col]))
            trsf.SetValue(row + 1, 4, float(translation[row]))
        transformed = BRepBuilderAPI_GTransform(shape.wrapped, trsf, True).Shape()
        return cq.Shape.cast(transformed)

    # Transform a local axis-aligned clipping box into the frame basis. Local
    # axes are width_axis, height_axis, and profile normal n.
    basis_matrix = [
        [width_axis.x, height_axis.x, n.x],
        [width_axis.y, height_axis.y, n.y],
        [width_axis.z, height_axis.z, n.z],
    ]

    def oriented_box(local_y0, local_y1):
        local_box = cq.Solid.makeBox(
            x1 - x0,
            local_y1 - local_y0,
            z1 - z0,
            cq.Vector(x0, local_y0, z0),
        )
        return affine_transform(local_box, basis_matrix)

    lower_box = oriented_box(ymin - margin, band_low)
    middle_box = oriented_box(band_low, band_high)
    upper_box = oriented_box(band_high, ymax + margin)

    lower = frame.intersect(lower_box)
    middle = frame.intersect(middle_box)
    upper = frame.intersect(upper_box)

    # Stretching is confined to a region where both side rails are straight and
    # prismatic, so their area profiles remain exactly unchanged.
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

    upper_shifted = upper.translate(
        cq.Vector(
            height_increase * h.x,
            height_increase * h.y,
            height_increase * h.z,
        )
    )

    result = lower.fuse(middle_extended).fuse(upper_shifted).removeSplitter()

    result_vertices = result.Vertices()
    final_y = [projection(v.Center(), height_axis) for v in result_vertices]
    final_height = max(final_y) - min(final_y)

    print(f"Input valid: {frame.isValid()}")
    print(f"Original frame height: {original_height:.6f} mm")
    print(f"Requested increase: {height_increase:.6f} mm")
    print(f"Final frame height: {final_height:.6f} mm")
    print(f"Measured increase: {final_height - original_height:.6f} mm")
    print(f"Output valid: {result.isValid()}")
    print(f"Output solids: {len(result.Solids())}")

    return cq.Workplane("XY").newObject([result])