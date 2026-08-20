def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    faces = model.Faces()
    solids = model.Solids()
    bbox = model.BoundingBox()
    print(f"Loaded model: valid={model.isValid()}, solids={len(solids)}, faces={len(faces)}")
    print(f"Overall bounds: x=({bbox.xmin:.3f}, {bbox.xmax:.3f}), y=({bbox.ymin:.3f}, {bbox.ymax:.3f}), z=({bbox.zmin:.3f}, {bbox.zmax:.3f})")

    # Bind the planning-stage FACE indices to the imported STEP topology and
    # inspect their actual positions before constructing the edit.
    target_indices = [14, 17, 71, 74]
    for index in target_indices:
        if index < len(faces):
            face = faces[index]
            fb = face.BoundingBox()
            fc = face.Center()
            try:
                normal = face.normalAt()
                normal_text = f"({normal.x:.4f}, {normal.y:.4f}, {normal.z:.4f})"
            except Exception:
                normal_text = "unavailable"
            print(
                f"FACE {index}: center=({fc.x:.3f}, {fc.y:.3f}, {fc.z:.3f}), "
                f"bounds=x({fb.xmin:.3f},{fb.xmax:.3f}) "
                f"y({fb.ymin:.3f},{fb.ymax:.3f}) "
                f"z({fb.zmin:.3f},{fb.zmax:.3f}), normal={normal_text}, "
                f"area={face.Area():.3f}"
            )

    if len(faces) <= 14:
        raise ValueError("Imported model does not contain the grounded FACE 14")

    rear_face = faces[14]
    rear_bounds = rear_face.BoundingBox()

    # FACE 14 is expected to be the approximately 292 x 344 mm planar rear
    # closure face. Guard against topology-order mismatch by comparing its two
    # in-plane spans and, if necessary, locating the best matching planar face.
    def rear_face_score(face):
        b = face.BoundingBox()
        dx, dy, dz = b.xlen, b.ylen, b.zlen
        thin_y = abs(dy)
        return abs(dx - 292.0) + abs(dz - 344.0) + 100.0 * thin_y

    if not (rear_bounds.xlen > 250.0 and rear_bounds.zlen > 300.0 and rear_bounds.ylen < 1.0):
        candidates = []
        for i, face in enumerate(faces):
            b = face.BoundingBox()
            if b.xlen > 250.0 and b.zlen > 300.0 and b.ylen < 1.0:
                candidates.append((rear_face_score(face), i, face))
        if not candidates:
            raise ValueError("Could not localize the large planar rear closure panel")
        candidates.sort(key=lambda item: item[0])
        _, selected_index, rear_face = candidates[0]
        rear_bounds = rear_face.BoundingBox()
        print(f"FACE 14 geometry did not match expected panel envelope; using inspected FACE {selected_index}")

    panel_x_center = (rear_bounds.xmin + rear_bounds.xmax) * 0.5
    panel_bottom = rear_bounds.zmin
    rear_y = (rear_bounds.ymin + rear_bounds.ymax) * 0.5

    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    cut_depth = 30.0

    # Lateral clearance is determined from the measured panel rather than a
    # hard-coded global coordinate. The same value is used as the nominal
    # bottom clearance, as required by the edit plan.
    lateral_clearance = max(0.0, (rear_bounds.xlen - opening_width) * 0.5)
    opening_bottom = panel_bottom + lateral_clearance
    opening_z_center = opening_bottom + opening_height * 0.5

    print(
        f"Rear opening placement: center=({panel_x_center:.3f}, {rear_y:.3f}, {opening_z_center:.3f}), "
        f"size={opening_width:.1f} x {opening_height:.1f} mm, radius={corner_radius:.1f} mm, "
        f"depth={cut_depth:.1f} mm, side/bottom clearance={lateral_clearance:.3f} mm"
    )

    # Construct the rounded rectangle on an XZ datum plane. Its normal points
    # inward from the semantic back toward +Y. A small rearward overlap avoids
    # leaving a coincident skin at the exterior face.
    start_y = rear_y - 0.10
    cut_plane = cq.Plane(
        origin=(panel_x_center, start_y, opening_z_center),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, 1.0, 0.0)
    )
    cutter_wp = (
        cq.Workplane(cut_plane)
        .rect(opening_width, opening_height)
        .vertices()
        .fillet(corner_radius)
        .extrude(cut_depth + 0.10)
    )
    cutter = cutter_wp.val()

    # SOLIDs 0-8 are section R01. Restrict subtraction to these enclosure,
    # closure-panel, chassis, and foot solids so controls and mechanisms in
    # sections R02-R05 cannot be modified. Both duplicated closure-panel solids
    # are therefore processed by the same cutter.
    edited_shapes = []
    cut_count = 0
    for solid_index, solid in enumerate(solids):
        if solid_index < 9:
            try:
                common = solid.intersect(cutter)
                if common.Volume() > 1.0e-6:
                    edited = solid.cut(cutter)
                    if not edited.isValid():
                        raise ValueError(f"Boolean result for SOLID {solid_index} is invalid")
                    edited_solids = edited.Solids()
                    if edited_solids:
                        edited_shapes.extend(edited_solids)
                    else:
                        edited_shapes.append(edited)
                    cut_count += 1
                    print(f"Cut R01 SOLID {solid_index}; removed volume={common.Volume():.3f} mm^3")
                else:
                    edited_shapes.append(solid)
            except Exception as exc:
                print(f"Boolean inspection failed for R01 SOLID {solid_index}: {exc}; attempting direct cut")
                edited = solid.cut(cutter)
                edited_solids = edited.Solids()
                edited_shapes.extend(edited_solids if edited_solids else [edited])
                cut_count += 1
        else:
            edited_shapes.append(solid)

    if cut_count == 0:
        raise ValueError("Rounded-rectangle cutter did not intersect any R01 solid")

    result = cq.Compound.makeCompound(edited_shapes)
    result_bbox = result.BoundingBox()
    print(f"Completed rear opening across {cut_count} R01 solids")
    print(f"Result: valid={result.isValid()}, solids={len(result.Solids())}, faces={len(result.Faces())}")
    print(f"Result bounds: x=({result_bbox.xmin:.3f},{result_bbox.xmax:.3f}), y=({result_bbox.ymin:.3f},{result_bbox.ymax:.3f}), z=({result_bbox.zmin:.3f},{result_bbox.zmax:.3f})")
    return result