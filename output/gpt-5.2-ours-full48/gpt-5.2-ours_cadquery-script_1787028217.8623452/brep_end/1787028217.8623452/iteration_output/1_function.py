def my_cad_function(args):
    import cadquery as cq
    import os

    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit task")

    input_file = os.path.expanduser(args["input_file"])
    bracket = cq.importers.importStep(input_file)

    shape = bracket.val() if hasattr(bracket, "val") else bracket
    bb = shape.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Bracket valid: {shape.isValid()}")
    print(f"Bracket bbox min=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) max=({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})")

    # --- Robustly identify the top boss bore cylinder using OCP adaptors ---
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    Y = cq.Vector(0, 1, 0)
    target_bore_r = 7.0175

    cyl_faces = bracket.faces("%CYLINDER").vals()
    print(f"Cylindrical faces found: {len(cyl_faces)}")

    candidates = []
    for i, f in enumerate(cyl_faces):
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                continue
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            ax1 = cyl.Axis()
            loc = ax1.Location()
            d = ax1.Direction()
            axis_origin = cq.Vector(loc.X(), loc.Y(), loc.Z())
            axis_dir = cq.Vector(d.X(), d.Y(), d.Z()).normalized()
            c = f.Center()
            center = cq.Vector(c.x, c.y, c.z)

            # Filter mostly-vertical cylinders (boss + holes). Use absolute because direction can flip.
            verticalness = abs(axis_dir.dot(Y))
            if verticalness < 0.95:
                continue

            # Score: prefer (1) near target radius, (2) near top of part (high y)
            # This separates top threaded bore from base mounting holes.
            score = abs(r - target_bore_r) + (bb.ymax - center.y) / 100.0
            candidates.append((score, r, center.y, axis_origin, axis_dir, f))
        except Exception:
            continue

    if not candidates:
        raise RuntimeError("Could not find any suitable vertical cylindrical faces to identify the top bore")

    candidates.sort(key=lambda t: t[0])
    best_score, bore_r, bore_center_y, axis_origin, axis_dir, bore_face = candidates[0]

    print("Top 6 cylinder candidates (score, radius, center_y):")
    for row in candidates[:6]:
        print(f"  score={row[0]:.4f}, r={row[1]:.4f}, center_y={row[2]:.2f}")

    # Ensure rod grows outward/upward from the bracket
    if axis_dir.dot(Y) < 0:
        axis_dir = axis_dir.multiply(-1)

    print(f"Selected bore radius={bore_r:.6f}, face_center_y={bore_center_y:.3f}")
    print(f"Bore axis origin=({axis_origin.x:.3f},{axis_origin.y:.3f},{axis_origin.z:.3f}) dir=({axis_dir.x:.6f},{axis_dir.y:.6f},{axis_dir.z:.6f})")

    # --- Compute intersection of the bore axis with the top plane at y=bb.ymax (boss top) ---
    if abs(axis_dir.y) < 1e-8:
        raise RuntimeError("Bore axis direction has ~zero Y component; cannot locate top mounting plane intersection")

    t_top = (bb.ymax - axis_origin.y) / axis_dir.y
    top_point = axis_origin.add(axis_dir.multiply(t_top))
    print(f"Top intersection point=({top_point.x:.3f},{top_point.y:.3f},{top_point.z:.3f}) (using y=bb.ymax)")

    # --- Parameters (mm) ---
    arm_length = 200.0          # exposed length above boss top
    engagement = 18.0           # inserted length into boss bore

    # Rod diameter: use bore-derived nominal (~2*bore_r), slightly rounded for robustness
    rod_d = round(2.0 * bore_r, 3)
    rod_r = rod_d / 2.0

    # Simple end feature for "ability to fix": a cross-hole near the free end for pin/clamp attachment
    cross_hole_d = 6.0
    cross_hole_r = cross_hole_d / 2.0
    hole_from_tip = 25.0

    print(f"Rod params: rod_d={rod_d:.3f}, arm_length={arm_length:.1f}, engagement={engagement:.1f}")

    # --- Build the rod as a NEW BODY aligned to the bore axis ---
    # Place base slightly inside the bore
    rod_base = top_point.add(axis_dir.multiply(-engagement))
    rod_total_len = arm_length + engagement

    rod_solid = cq.Solid.makeCylinder(rod_r, rod_total_len, rod_base, axis_dir)
    rod_wp = cq.Workplane(obj=rod_solid)

    # Chamfer rod tip + stud end (best-effort)
    def proj(v):
        return v.dot(axis_dir)

    try:
        tip_face = rod_wp.faces("%PLANE").sort(lambda f: proj(f.Center())).last()
        rod_wp = tip_face.edges().chamfer(1.0)
    except Exception as e:
        print(f"Tip chamfer skipped: {e}")

    try:
        stud_face = rod_wp.faces("%PLANE").sort(lambda f: proj(f.Center())).first()
        rod_wp = stud_face.edges().chamfer(1.0)
    except Exception as e:
        print(f"Stud chamfer skipped: {e}")

    # Cross-hole near free end
    # Choose a stable perpendicular direction
    ref = cq.Vector(1, 0, 0)
    perp = axis_dir.cross(ref)
    if perp.Length < 1e-6:
        perp = axis_dir.cross(cq.Vector(0, 0, 1))
    perp = perp.normalized()

    rod_tip = rod_base.add(axis_dir.multiply(rod_total_len))
    hole_center = rod_tip.add(axis_dir.multiply(-hole_from_tip))
    hole_len = rod_d * 3.0
    hole_base = hole_center.add(perp.multiply(-hole_len / 2.0))
    hole_cyl = cq.Solid.makeCylinder(cross_hole_r, hole_len, hole_base, perp)
    rod_wp = rod_wp.cut(hole_cyl)

    # --- Return assembly: bracket + fixation rod ---
    assy = cq.Assembly()
    assy.add(bracket, name="bracket")
    assy.add(rod_wp.val(), name="fixation_rod", color=cq.Color(1.0, 0.75, 0.2))
    return assy
