def my_cad_function(args):
    import cadquery as cq
    import os
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    # ---- Load base model ----
    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for this edit task")

    input_file = os.path.expanduser(args["input_file"])
    base_wp = cq.importers.importStep(input_file)
    base_shape = base_wp.val() if hasattr(base_wp, "val") else base_wp

    bbox = base_shape.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Base bbox: xmin={bbox.xmin:.3f}, xmax={bbox.xmax:.3f}, ymin={bbox.ymin:.3f}, ymax={bbox.ymax:.3f}, zmin={bbox.zmin:.3f}, zmax={bbox.zmax:.3f}")
    print(f"Faces: {len(base_shape.Faces())}")

    # ---- Find the clevis pin-bore cylinder (R~3, axis ~global Y, located at negative X) ----
    candidates = []
    for i, f in enumerate(base_shape.Faces()):
        try:
            wrapped = f.wrapped  # TopoDS_Face
            ad = BRepAdaptor_Surface(wrapped)
            st = ad.GetType()
            if st != GeomAbs_SurfaceType.GeomAbs_Cylinder:
                continue

            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            ax = cyl.Axis()  # gp_Ax1
            p = ax.Location()  # gp_Pnt
            d = ax.Direction()  # gp_Dir
            dx, dy, dz = float(d.X()), float(d.Y()), float(d.Z())

            # Filter: radius close to 3mm, axis along Y, and at negative X (clevis end)
            if abs(r - 3.0) > 0.10:
                continue
            if not (abs(dy) > 0.98 and abs(dx) < 0.10 and abs(dz) < 0.10):
                continue
            if float(p.X()) > 0.0:
                continue

            candidates.append({
                "face_index": i,
                "radius": r,
                "px": float(p.X()),
                "py": float(p.Y()),
                "pz": float(p.Z()),
                "dx": dx,
                "dy": dy,
                "dz": dz,
            })
        except Exception:
            continue

    print(f"Cylindrical bore candidates (R~3, axis~Y, x<0): {len(candidates)}")
    for c in sorted(candidates, key=lambda x: x["px"])[:10]:
        print(f"  face[{c['face_index']}]: R={c['radius']:.4f}, axisP=({c['px']:.3f},{c['py']:.3f},{c['pz']:.3f}), dir=({c['dx']:.3f},{c['dy']:.3f},{c['dz']:.3f})")

    if not candidates:
        raise RuntimeError("Could not find clevis bore cylindrical face (R~3, axis~Y, x<0).")

    # Choose the most negative-X candidate as the clevis pin bore
    bore = min(candidates, key=lambda x: x["px"])

    bore_axis_point = (bore["px"], bore["py"], bore["pz"])
    print(f"Selected bore face[{bore['face_index']}], axis point: {bore_axis_point}, R={bore['radius']:.4f}")

    # ---- Pin parameters ----
    # Clearance for free rotation (slightly under 6.00mm)
    pin_diameter = 5.98

    # Length: span full part width + small protrusion both sides
    base_width_y = (bbox.ymax - bbox.ymin)
    protrusion_each_side = 2.0
    pin_length = base_width_y + 2.0 * protrusion_each_side

    chamfer = 0.5

    print(f"Pin: dia={pin_diameter:.3f} mm, length={pin_length:.3f} mm (base_width_y={base_width_y:.3f} + 2*{protrusion_each_side})")

    # ---- Build pin as a NEW BODY (separate from link arm) ----
    # Create a plane normal to Y (global), located at the bore axis point.
    # Use xDir along +X, so the sketch plane is effectively XZ.
    pin_plane = cq.Plane(origin=bore_axis_point, xDir=(1, 0, 0), normal=(0, 1, 0))

    pin_wp = (
        cq.Workplane(pin_plane)
        .circle(pin_diameter / 2.0)
        .extrude(pin_length / 2.0, both=True)
    )

    # Chamfer both ends for lead-in
    try:
        pin_wp = pin_wp.faces("|Y").edges().chamfer(chamfer)
    except Exception as e:
        print(f"Warning: chamfer failed ({e}); continuing without chamfer.")

    # ---- Return as assembly to preserve rotational DOF intent ----
    asm = cq.Assembly()
    asm.add(base_wp, name="link_arm")
    asm.add(pin_wp, name="pin")

    return asm
