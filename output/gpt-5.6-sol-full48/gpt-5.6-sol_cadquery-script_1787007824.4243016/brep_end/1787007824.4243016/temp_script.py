def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # The frame thickness direction is rotated 15 degrees from global Y.
    # Rotate it into global Z so a local prismatic stretch can be performed.
    align_angle = 105.0
    aligned = original.rotate((0, 0, 0), (1, 0, 0), align_angle)

    # Find the two broad annular datum faces after alignment. They are the only
    # substantial planar faces whose normals are parallel to global Z.
    broad_faces = []
    for face in aligned.Faces():
        if face.geomType() != "PLANE":
            continue
        center = face.Center()
        try:
            normal = face.normalAt(center)
        except Exception:
            normal = face.normalAt()
        if abs(normal.z) > 0.9999:
            broad_faces.append((face.Area(), center.z, normal.z))

    if len(broad_faces) < 2:
        raise RuntimeError("Could not identify both broad annular frame faces")

    broad_faces.sort(key=lambda item: item[0], reverse=True)
    primary = broad_faces[0]
    secondary = max(
        broad_faces[1:],
        key=lambda item: abs(item[1] - primary[1])
    )

    primary_z = primary[1]
    secondary_z = secondary[1]
    direction = 1.0 if secondary_z > primary_z else -1.0
    old_land_separation = abs(secondary_z - primary_z)

    # Stretch a short prismatic region midway between the two annular lands.
    # The primary side remains fixed, the complete secondary-side termination
    # moves 5 mm, and all in-plane dimensions and rounded end treatments remain
    # unchanged.
    increase = 5.0
    cut_z = 0.5 * (primary_z + secondary_z)
    slice_thickness = 1.0

    bbox = aligned.BoundingBox()
    margin = 20.0
    box_x = bbox.xlen + 2.0 * margin
    box_y = bbox.ylen + 2.0 * margin
    xc = 0.5 * (bbox.xmin + bbox.xmax)
    yc = 0.5 * (bbox.ymin + bbox.ymax)

    if direction > 0:
        fixed_min = bbox.zmin - margin
        fixed_max = cut_z
        slice_min = cut_z
        slice_max = cut_z + slice_thickness
        moving_min = slice_max
        moving_max = bbox.zmax + margin
        translation = increase
        scale_origin = slice_min
    else:
        fixed_min = cut_z
        fixed_max = bbox.zmax + margin
        slice_min = cut_z - slice_thickness
        slice_max = cut_z
        moving_min = bbox.zmin - margin
        moving_max = slice_min
        translation = -increase
        scale_origin = slice_max

    def clipping_box(zmin, zmax):
        return (
            cq.Workplane("XY")
            .box(box_x, box_y, zmax - zmin)
            .translate((xc, yc, 0.5 * (zmin + zmax)))
            .val()
        )

    fixed_part = aligned.intersect(clipping_box(fixed_min, fixed_max))
    stretch_part = aligned.intersect(clipping_box(slice_min, slice_max))
    moving_part = aligned.intersect(clipping_box(moving_min, moving_max))

    stretch_factor = (slice_thickness + increase) / slice_thickness
    z_scale = stretch_factor
    z_offset = scale_origin * (1.0 - stretch_factor)
    stretch_matrix = cq.Matrix([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, z_scale, z_offset],
        [0.0, 0.0, 0.0, 1.0]
    ])
    stretched_part = stretch_part.transformGeometry(stretch_matrix)
    moved_part = moving_part.translate((0.0, 0.0, translation))

    result_aligned = fixed_part.fuse(stretched_part).fuse(moved_part).clean()
    result = result_aligned.rotate((0, 0, 0), (1, 0, 0), -align_angle).clean()

    if not result.isValid():
        raise RuntimeError("The stretched frame is not a valid solid")

    final_aligned = result.rotate((0, 0, 0), (1, 0, 0), align_angle)
    final_bbox = final_aligned.BoundingBox()

    print(f"Original valid: {original.isValid()}")
    print(f"Result valid: {result.isValid()}")
    print(f"Original broad-land separation: {old_land_separation:.6f} mm")
    print(f"Requested increase: {increase:.6f} mm")
    print(f"Expected final broad-land separation: {old_land_separation + increase:.6f} mm")
    print(f"Result volume: {result.Volume():.6f} mm^3")
    print(f"Result faces: {len(result.Faces())}")
    print(f"Aligned result bbox: x={final_bbox.xlen:.6f}, y={final_bbox.ylen:.6f}, z={final_bbox.zlen:.6f} mm")

    return cq.Workplane(obj=result)
