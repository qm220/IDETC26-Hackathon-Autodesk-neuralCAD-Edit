def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val()
    solids = list(base_shape.Solids())
    faces = list(base_shape.Faces())

    print(f"Imported model: valid={base_shape.isValid()}, solids={len(solids)}, faces={len(faces)}")

    # The prior iteration placed cutters from the overall bounding-box extrema.
    # Those extrema include peripheral features and did not reliably coincide
    # with the intended tank faces. Resolve the actual planned B-rep faces here.
    def describe_face(index):
        f = faces[index]
        bb = f.BoundingBox()
        c = f.Center()
        try:
            n = f.normalAt()
        except Exception:
            n = cq.Vector(0, 0, 0)
        print(
            f"FACE {index}: area={f.Area():.2f}, center=({c.x:.2f},{c.y:.2f},{c.z:.2f}), "
            f"normal=({n.x:.3f},{n.y:.3f},{n.z:.3f}), "
            f"bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f})"
        )
        return f

    planned_top = describe_face(46) if len(faces) > 46 else None
    planned_bottom = describe_face(22) if len(faces) > 22 else None

    # Locate the main radiator solid for fallback face selection.
    def radiator_score(s):
        bb = s.BoundingBox()
        return (bb.ylen * bb.zlen) / max(bb.xlen, 1.0)

    radiator = max(solids, key=radiator_score)
    rbb = radiator.BoundingBox()
    print(
        f"Radiator bbox: X=({rbb.xmin:.2f},{rbb.xmax:.2f}), "
        f"Y=({rbb.ymin:.2f},{rbb.ymax:.2f}), "
        f"Z=({rbb.zmin:.2f},{rbb.zmax:.2f})"
    )

    def usable_y_face(face, sign):
        if face is None:
            return False
        bb = face.BoundingBox()
        try:
            n = face.normalAt()
        except Exception:
            return False
        return n.y * sign > 0.70 and bb.zlen > 250.0 and bb.xlen > 20.0

    def find_fallback(sign):
        candidates = []
        for f in radiator.Faces():
            bb = f.BoundingBox()
            try:
                n = f.normalAt()
            except Exception:
                continue
            if n.y * sign > 0.70 and bb.zlen > rbb.zlen * 0.65 and bb.xlen > 20.0:
                score = f.Area() + 20.0 * bb.zlen + 5.0 * bb.xlen
                candidates.append((score, f))
        if not candidates:
            raise ValueError(f"Could not locate {'top' if sign > 0 else 'bottom'} Y-normal tank face")
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    top_face = planned_top if usable_y_face(planned_top, 1) else find_fallback(1)
    bottom_face = planned_bottom if usable_y_face(planned_bottom, -1) else find_fallback(-1)

    def face_data(label, face):
        bb = face.BoundingBox()
        c = face.Center()
        n = face.normalAt()
        print(
            f"Selected {label}: center=({c.x:.2f},{c.y:.2f},{c.z:.2f}), "
            f"normal=({n.x:.3f},{n.y:.3f},{n.z:.3f}), "
            f"bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f}), area={face.Area():.2f}"
        )
        return bb, c

    top_bb, top_center = face_data("top face", top_face)
    bottom_bb, bottom_center = face_data("bottom face", bottom_face)

    slot_length = 36.0
    slot_width = 7.0
    slot_depth = 1.15
    outside_overlap = 0.30

    def capsule_y(xc, zc, face_y, inward_sign):
        radius = slot_width * 0.5
        straight = slot_length - slot_width
        total_depth = slot_depth + outside_overlap

        if inward_sign < 0:  # top face, cut toward -Y
            y0 = face_y - slot_depth
        else:                # bottom face, cut toward +Y
            y0 = face_y - outside_overlap

        box = cq.Solid.makeBox(
            straight,
            total_depth,
            slot_width,
            cq.Vector(xc - straight * 0.5, y0, zc - radius)
        )
        cap1 = cq.Solid.makeCylinder(
            radius,
            total_depth,
            cq.Vector(xc - straight * 0.5, y0, zc),
            cq.Vector(0, 1, 0)
        )
        cap2 = cq.Solid.makeCylinder(
            radius,
            total_depth,
            cq.Vector(xc + straight * 0.5, y0, zc),
            cq.Vector(0, 1, 0)
        )
        return box.fuse(cap1).fuse(cap2)

    def pattern_positions(face_bb, nominal_pitch=27.0):
        margin = max(22.0, face_bb.zlen * 0.055)
        zmin = face_bb.zmin + margin
        zmax = face_bb.zmax - margin
        span = zmax - zmin
        count = max(9, int(span / nominal_pitch) + 1)
        pitch = span / float(count - 1)
        return [zmin + i * pitch for i in range(count)], pitch

    top_positions, top_pitch = pattern_positions(top_bb)
    bottom_positions, bottom_pitch = pattern_positions(bottom_bb)

    top_x = (top_bb.xmin + top_bb.xmax) * 0.5
    bottom_x = (bottom_bb.xmin + bottom_bb.xmax) * 0.5

    # Resolve each side independently. The top omits the filler-neck region and
    # the +Z mounting region; the bottom omits the diagonally opposed -Z mount.
    top_cutters = []
    top_used = []
    top_center_z = (top_bb.zmin + top_bb.zmax) * 0.5
    top_end_margin = max(22.0, top_bb.zlen * 0.055)
    for z in top_positions:
        if abs(z - top_center_z) < max(23.0, top_pitch * 0.80):
            continue
        if z > top_bb.zmax - top_end_margin * 1.25:
            continue
        top_cutters.append(capsule_y(top_x, z, top_center.y, -1))
        top_used.append(z)

    bottom_cutters = []
    bottom_used = []
    bottom_end_margin = max(22.0, bottom_bb.zlen * 0.055)
    for z in bottom_positions:
        if z < bottom_bb.zmin + bottom_end_margin * 1.25:
            continue
        bottom_cutters.append(capsule_y(bottom_x, z, bottom_center.y, 1))
        bottom_used.append(z)

    all_cutters = top_cutters + bottom_cutters
    print(
        f"Slots: length={slot_length:.2f}, width={slot_width:.2f}, depth={slot_depth:.2f}; "
        f"top={len(top_used)}, bottom={len(bottom_used)}"
    )

    # Cut each imported solid independently. This avoids unreliable booleans on
    # the original invalid multi-solid compound and preserves unrelated parts.
    edited_solids = []
    changed_solids = 0
    total_removed = 0.0

    for solid_index, solid in enumerate(solids):
        before = solid.Volume()
        result = solid
        for cutter in all_cutters:
            try:
                result = result.cut(cutter)
            except Exception as exc:
                print(f"Boolean warning on solid {solid_index}: {exc}")
        after = result.Volume()
        removed = max(0.0, before - after)
        if removed > 0.01:
            changed_solids += 1
            total_removed += removed
            print(f"Solid {solid_index}: removed volume={removed:.3f}")
        edited_solids.extend(result.Solids())

    if total_removed <= 0.01:
        raise ValueError("Slot cutters removed no material from the selected top and bottom surfaces")

    edited_shape = cq.Compound.makeCompound(edited_solids)
    print(
        f"Edited model: changed_solids={changed_solids}, removed_volume={total_removed:.3f}, "
        f"solids={len(edited_shape.Solids())}, faces={len(edited_shape.Faces())}, "
        f"valid={edited_shape.isValid()}"
    )

    return cq.Workplane(obj=edited_shape)
