def my_cad_function(args):
    import cadquery as cq
    import os, math

    thickness = 2.54  # mm (0.254 cm)

    if "input_file" not in args:
        raise ValueError("Missing args['input_file'] for STEP import")

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    # Get underlying OCC shape
    if isinstance(model, cq.Assembly):
        base_shape = model.toCompound()
    else:
        base_shape = model.val() if hasattr(model, "val") else model

    if not hasattr(base_shape, "Faces"):
        raise ValueError("Imported shape does not expose Faces(); cannot proceed")

    faces = list(base_shape.Faces())
    planar_faces = [f for f in faces if getattr(f, "geomType", lambda: None)() == "PLANE"]

    bbox = base_shape.BoundingBox()
    top_y = bbox.ymax
    bot_y = bbox.ymin

    print(f"Imported faces: {len(faces)}; planar faces: {len(planar_faces)}")
    print(f"BBox y-range: {bbox.ymin:.3f} .. {bbox.ymax:.3f}")

    if not planar_faces:
        raise ValueError("No planar faces found; cannot create covers")

    # Pick the actual outer top/bottom faces: planar, constant y, at bbox extremes, largest area
    def is_at_y_extreme(f, yval, tol=1e-4):
        fb = f.BoundingBox()
        return (abs(fb.ymin - yval) < tol) and (abs(fb.ymax - yval) < tol)

    top_candidates = [f for f in planar_faces if is_at_y_extreme(f, top_y)]
    bot_candidates = [f for f in planar_faces if is_at_y_extreme(f, bot_y)]

    if not top_candidates:
        # fall back: choose maximal center-y planar face
        top_face = max(planar_faces, key=lambda ff: ff.Center().y)
        print("WARN: No planar face exactly at bbox.ymax; falling back to max Center().y")
    else:
        top_face = max(top_candidates, key=lambda ff: ff.Area())

    if not bot_candidates:
        bot_face = min(planar_faces, key=lambda ff: ff.Center().y)
        print("WARN: No planar face exactly at bbox.ymin; falling back to min Center().y")
    else:
        bot_face = max(bot_candidates, key=lambda ff: ff.Area())

    print(f"Top face chosen: centerY={top_face.Center().y:.3f}, area={top_face.Area():.3f}")
    print(f"Bottom face chosen: centerY={bot_face.Center().y:.3f}, area={bot_face.Area():.3f}")

    def wire_area(w):
        # area magnitude (planar wire)
        try:
            return abs(cq.Face.makeFromWires(w).Area())
        except Exception:
            return 0.0

    def wires_from_section_at_y(y, eps=0.0):
        # Section on an XZ plane at y; returns list of wires (may be empty)
        pl = cq.Plane(origin=(0, y + eps, 0), normal=(0, 1, 0))
        wp = cq.Workplane(pl).add(base_shape).section()
        return list(wp.vals()) if hasattr(wp, "vals") else []

    def build_profile_wires(face_at_plane, y_plane):
        """Return (outerWire, innerWires) that best represent the clamp outer contour at that plane.
        Preference order:
          1) face.outerWire + face.innerWires if inner wires exist
          2) section() wires at that y, choose largest as outer and rest as inner
          3) face.outerWire only
        """
        outer = face_at_plane.outerWire()
        inners = list(face_at_plane.innerWires())
        print(f"Face@Y={y_plane:.3f}: innerWires={len(inners)}")

        if len(inners) > 0:
            return outer, inners

        # Try to recover hole loops (and/or validate outline) using a section at the same plane
        sec_wires = wires_from_section_at_y(y_plane, eps=0.0)
        if len(sec_wires) >= 2:
            # choose largest by area as outer
            areas = [(wire_area(w), i, w) for i, w in enumerate(sec_wires)]
            areas.sort(key=lambda t: t[0], reverse=True)
            sec_outer = areas[0][2]
            sec_inners = [t[2] for t in areas[1:] if t[0] > 1e-6]
            print(f"Section@Y={y_plane:.3f}: wires={len(sec_wires)} outerArea={areas[0][0]:.3f} innerCount={len(sec_inners)}")
            return sec_outer, sec_inners
        elif len(sec_wires) == 1:
            print(f"Section@Y={y_plane:.3f}: wires=1 (no inner loops detected)")
            # If the single section wire differs from face.outerWire, prefer section for robustness
            return sec_wires[0], []

        print(f"Section@Y={y_plane:.3f}: no wires found; using face.outerWire only")
        return outer, []

    def make_cover_from_face(face_at_plane, y_plane, extrude_vec, name):
        outerW, innerWs = build_profile_wires(face_at_plane, y_plane)
        cover_face = cq.Face.makeFromWires(outerW, innerWs)
        cover_solid = cq.Solid.extrudeLinear(cover_face, extrude_vec)
        print(f"{name}: thickness={thickness:.3f}mm, innerCutouts={len(innerWs)}")
        return cover_solid

    cover_upper = make_cover_from_face(top_face, top_face.Center().y, cq.Vector(0, thickness, 0), "Cover_Upper")
    cover_lower = make_cover_from_face(bot_face, bot_face.Center().y, cq.Vector(0, -thickness, 0), "Cover_Lower")

    assy = cq.Assembly(name="Cross_strut_clamp_with_covers")
    assy.add(base_shape, name="Base")
    assy.add(cover_upper, name="Cover_Upper", color=cq.Color(0.82, 0.82, 0.88))
    assy.add(cover_lower, name="Cover_Lower", color=cq.Color(0.82, 0.82, 0.88))

    return assy
