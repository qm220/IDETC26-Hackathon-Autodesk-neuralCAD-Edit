def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val()
    solids = source.Solids()

    if len(solids) != 2:
        raise ValueError(f"Expected two solids in the source model, found {len(solids)}")

    # Identify the small central insert and the large sprocket body by volume.
    solids = sorted(solids, key=lambda s: s.Volume())
    old_insert = solids[0]
    old_body = solids[1]

    ibb = old_insert.BoundingBox()
    axis_x = 0.5 * (ibb.xmin + ibb.xmax)
    axis_z = 0.5 * (ibb.zmin + ibb.zmax)
    rear_y = ibb.ymin

    # Find the large internal planar shoulder of the insert. In the source part
    # this is approximately y=0.175 mm and marks the end of the flower-shaped
    # engagement region.
    shoulder_candidates = []
    for face in old_insert.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            center = face.Center()
            normal = face.normalAt(center)
            if (
                abs(normal.y) > 0.98
                and rear_y + 0.5 < center.y < ibb.ymax - 0.5
                and face.Area() > 50.0
            ):
                shoulder_candidates.append((face.Area(), center.y))
        except Exception:
            pass

    if shoulder_candidates:
        # The intended intermediate shoulder is the largest qualifying face.
        engagement_front_y = max(shoulder_candidates, key=lambda item: item[0])[1]
    else:
        engagement_front_y = rear_y + 4.8

    print(f"Imported STEP: {input_file}")
    print(f"Source solid count: {len(solids)}")
    print(f"Insert engagement interval: y={rear_y:.6f} to {engagement_front_y:.6f}")

    def axial_prism(workplane_object, y_start, y_end):
        """Place an XZ sketch at y_start and extrude it in +Y."""
        return workplane_object.extrude(y_end - y_start).val()

    def xz_plane(y):
        return cq.Workplane(
            cq.Plane(
                origin=(axis_x, y, axis_z),
                xDir=(1, 0, 0),
                normal=(0, 1, 0),
            )
        )

    # The source flower envelope is about 31.5 mm across. A 26.0 mm
    # across-flats regular hexagon has 30.02 mm across corners, so it remains
    # inside that envelope while retaining material outside the spline roots.
    insert_across_flats = 26.00
    assembly_clearance = 0.30
    seat_across_flats = insert_across_flats + assembly_clearance
    insert_corner_diameter = insert_across_flats / math.cos(math.radians(30.0))
    seat_corner_diameter = seat_across_flats / math.cos(math.radians(30.0))

    overlap = 0.03
    tool_margin = 0.10

    # Remove the complete old flower engagement portion from the insert while
    # retaining its circular front flange, clamping shoulder, and spline body.
    removal_tool = axial_prism(
        xz_plane(rear_y - tool_margin).circle(40.0),
        rear_y - tool_margin,
        engagement_front_y + overlap,
    )
    retained_insert = old_insert.cut(removal_tool)

    # Recover the exact source spline void within a core cylinder. Subtracting
    # this void from the replacement prism preserves the original fine spline
    # count, pitch, root form, and coaxial alignment without recreating it.
    spline_capture_radius = 12.0
    spline_capture = axial_prism(
        xz_plane(rear_y - tool_margin).circle(spline_capture_radius),
        rear_y - tool_margin,
        engagement_front_y + 2.0 * overlap,
    )
    exact_spline_void = spline_capture.cut(old_insert)

    replacement_hex = axial_prism(
        xz_plane(rear_y).polygon(6, insert_corner_diameter),
        rear_y,
        engagement_front_y + 2.0 * overlap,
    )
    replacement_hex = replacement_hex.cut(exact_spline_void)
    new_insert = retained_insert.fuse(replacement_hex)

    # Heal the matching hub seat by filling the former lobed cavity locally.
    # The patch overlaps the existing annular hub, but does not extend into the
    # spoke network. It is then cut with a matching clearance hexagon.
    hub_patch_radius = 16.50
    hub_patch = axial_prism(
        xz_plane(rear_y - overlap).circle(hub_patch_radius),
        rear_y - overlap,
        engagement_front_y + overlap,
    )
    patched_body = old_body.fuse(hub_patch)

    seat_tool = axial_prism(
        xz_plane(rear_y - tool_margin).polygon(6, seat_corner_diameter),
        rear_y - tool_margin,
        engagement_front_y + 2.0 * tool_margin,
    )
    new_body = patched_body.cut(seat_tool)

    # Validate that the edited components remain separate, valid solids.
    if not new_insert.isValid():
        raise ValueError("The replacement hexagonal insert is not a valid solid")
    if not new_body.isValid():
        raise ValueError("The modified sprocket body is not a valid solid")

    interference = new_insert.intersect(new_body)
    interference_volume = interference.Volume() if not interference.isNull() else 0.0

    result = cq.Compound.makeCompound([new_insert, new_body])
    result_solids = result.Solids()

    print(f"Hex insert across flats: {insert_across_flats:.3f} mm")
    print(f"Hex hub seat across flats: {seat_across_flats:.3f} mm")
    print(f"Nominal diametral clearance: {assembly_clearance:.3f} mm")
    print(f"Result solid count: {len(result_solids)}")
    print(f"Insert volume: {new_insert.Volume():.6f} mm^3")
    print(f"Body volume: {new_body.Volume():.6f} mm^3")
    print(f"Insert/body interference volume: {interference_volume:.9f} mm^3")
    print(f"Result valid: {result.isValid()}")

    return cq.Workplane("XY").newObject([result])