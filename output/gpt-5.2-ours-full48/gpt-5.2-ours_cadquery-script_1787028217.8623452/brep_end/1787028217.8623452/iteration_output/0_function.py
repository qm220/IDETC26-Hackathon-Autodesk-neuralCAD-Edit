def my_cad_function(args):
    import cadquery as cq
    import os
    from math import sqrt

    # --- Load the existing bracket STEP ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit task")
    input_file = os.path.expanduser(args["input_file"])
    bracket = cq.importers.importStep(input_file)

    shape = bracket.val() if hasattr(bracket, "val") else bracket
    bb = shape.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Bracket valid: {shape.isValid()}")
    print(f"Bracket bbox min=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) max=({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})")

    # --- Find the boss bore cylindrical face (expected radius ~7.0175) and extract its axis ---
    # Use OCP to robustly read cylinder axis
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    target_bore_r = 7.0175
    cyl_faces = bracket.faces("%CYLINDER").vals()
    print(f"Cylindrical faces found: {len(cyl_faces)}")

    best = None
    for f in cyl_faces:
        try:
            r = f.radius()
        except Exception:
            continue
        # prefer small-ish cylinders near the expected bore radius
        score = abs(r - target_bore_r)
        if best is None or score < best[0]:
            best = (score, r, f)

    if best is None:
        raise RuntimeError("No cylindrical faces found / could not identify bore")

    bore_face = best[2]
    bore_r = best[1]
    print(f"Selected bore candidate cylinder radius={bore_r:.6f} (score={best[0]:.6f})")

    ad = BRepAdaptor_Surface(bore_face.wrapped)
    if ad.GetType() != GeomAbs_Cylinder:
        raise RuntimeError("Selected face is not a cylinder according to adaptor")
    cyl = ad.Cylinder()
    ax1 = cyl.Axis()
    loc = ax1.Location()
    d = ax1.Direction()

    axis_origin = cq.Vector(loc.X(), loc.Y(), loc.Z())
    axis_dir = cq.Vector(d.X(), d.Y(), d.Z())
    axis_dir = axis_dir.normalized()
    print(f"Bore axis origin=({axis_origin.x:.3f},{axis_origin.y:.3f},{axis_origin.z:.3f}) dir=({axis_dir.x:.6f},{axis_dir.y:.6f},{axis_dir.z:.6f})")

    # --- Find the top planar face normal to the bore axis at the extreme +axis_dir side ---
    # We identify the 'top' as the planar face whose normal is parallel to axis_dir and whose center
    # has the maximum projection along axis_dir.
    plane_faces = bracket.faces("%PLANE").vals()
    print(f"Planar faces found: {len(plane_faces)}")

    def proj(v: cq.Vector, direction: cq.Vector):
        return v.dot(direction)

    # bbox extreme projection along axis_dir
    corners = [
        cq.Vector(bb.xmin, bb.ymin, bb.zmin),
        cq.Vector(bb.xmin, bb.ymin, bb.zmax),
        cq.Vector(bb.xmin, bb.ymax, bb.zmin),
        cq.Vector(bb.xmin, bb.ymax, bb.zmax),
        cq.Vector(bb.xmax, bb.ymin, bb.zmin),
        cq.Vector(bb.xmax, bb.ymin, bb.zmax),
        cq.Vector(bb.xmax, bb.ymax, bb.zmin),
        cq.Vector(bb.xmax, bb.ymax, bb.zmax),
    ]
    max_proj = max(proj(c, axis_dir) for c in corners)
    min_proj = min(proj(c, axis_dir) for c in corners)
    print(f"BBox projection along axis_dir: min={min_proj:.3f}, max={max_proj:.3f}")

    top_face = None
    top_face_center = None
    top_face_normal = None
    top_score = None

    for f in plane_faces:
        c = f.Center()
        # use the normal at center
        try:
            n = f.normalAt(c)
        except Exception:
            continue
        n = cq.Vector(n.x, n.y, n.z).normalized()
        # must be (nearly) parallel to axis_dir (either direction)
        if abs(n.dot(axis_dir)) < 0.95:
            continue
        p = proj(cq.Vector(c.x, c.y, c.z), axis_dir)
        # prefer faces closest to the +extreme
        score = abs(max_proj - p)
        if top_score is None or score < top_score:
            top_score = score
            top_face = f
            top_face_center = cq.Vector(c.x, c.y, c.z)
            top_face_normal = n

    if top_face is None:
        raise RuntimeError("Could not identify a top planar face normal to the bore axis")

    # Ensure rod points outward from the bracket: choose direction consistent with face normal
    rod_dir = axis_dir if top_face_normal.dot(axis_dir) > 0 else axis_dir.multiply(-1)
    print(f"Top face center=({top_face_center.x:.3f},{top_face_center.y:.3f},{top_face_center.z:.3f})")
    print(f"Top face normal=({top_face_normal.x:.6f},{top_face_normal.y:.6f},{top_face_normal.z:.6f}); using rod_dir=({rod_dir.x:.6f},{rod_dir.y:.6f},{rod_dir.z:.6f})")

    # --- Parameters (mm) ---
    arm_length = 200.0              # exposed length above boss top
    engagement = 18.0               # approximate thread engagement into the bore
    rod_d = 14.0                    # nominal rod/stud diameter (matches ~14mm from planning)
    rod_r = rod_d / 2.0

    # Simple end feature: cross-hole near the free end to attach a clamp/pin
    cross_hole_d = 6.0
    cross_hole_r = cross_hole_d / 2.0
    hole_from_top = 25.0            # location from rod tip

    # --- Build rod as a separate solid aligned to the boss bore axis ---
    # Cylinder base point placed 'inside' the bore by engagement distance.
    rod_base = top_face_center.add(rod_dir.multiply(-engagement))
    rod_total_len = arm_length + engagement

    rod_solid = cq.Solid.makeCylinder(rod_r, rod_total_len, rod_base, rod_dir)
    rod_wp = cq.Workplane(obj=rod_solid)

    # Add a small chamfer on the exposed rod tip edge
    # Find the furthest planar face along rod_dir (rod tip) and chamfer its outer edge.
    try:
        tip_face = rod_wp.faces("%PLANE").sort(lambda f: proj(f.Center(), rod_dir)).last()
        rod_wp = tip_face.edges().chamfer(1.0)
    except Exception as e:
        print(f"Tip chamfer skipped: {e}")

    # Add lead-in chamfer on the stud end (the inserted end)
    try:
        stud_end_face = rod_wp.faces("%PLANE").sort(lambda f: proj(f.Center(), rod_dir)).first()
        rod_wp = stud_end_face.edges().chamfer(1.0)
    except Exception as e:
        print(f"Stud chamfer skipped: {e}")

    # Cross-hole near the free end, direction perpendicular to rod_dir
    # Choose a stable perpendicular vector.
    xref = cq.Vector(1, 0, 0)
    perp = rod_dir.cross(xref)
    if perp.Length < 1e-6:
        perp = rod_dir.cross(cq.Vector(0, 0, 1))
    perp = perp.normalized()

    rod_tip = rod_base.add(rod_dir.multiply(rod_total_len))
    hole_center = rod_tip.add(rod_dir.multiply(-hole_from_top))
    hole_len = rod_d * 3.0
    hole_base = hole_center.add(perp.multiply(-hole_len / 2.0))
    hole_cyl = cq.Solid.makeCylinder(cross_hole_r, hole_len, hole_base, perp)

    rod_wp = rod_wp.cut(hole_cyl)

    # --- Return as an assembly (bracket + separate fixation rod) ---
    assy = cq.Assembly()
    assy.add(bracket, name="bracket")
    assy.add(rod_wp.val(), name="fixation_rod", color=cq.Color(1.0, 0.75, 0.2))

    return assy
