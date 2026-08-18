def my_cad_function(args):
    import cadquery as cq
    import os
    from cadquery import Vector

    # --- Load input STEP ---
    input_path = args.get("input_file", None)
    if not input_path or not os.path.exists(os.path.expanduser(input_path)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_path}")

    input_path = os.path.expanduser(input_path)
    base_wp = cq.importers.importStep(input_path)
    base_shape = base_wp.val() if hasattr(base_wp, 'val') else base_wp

    print(f"Loaded STEP: {input_path}")
    print(f"Valid: {base_shape.isValid()}")

    bbox = base_shape.BoundingBox()
    bc = bbox.center
    print(f"BBox min=({bbox.xmin:.3f},{bbox.ymin:.3f},{bbox.zmin:.3f}) max=({bbox.xmax:.3f},{bbox.ymax:.3f},{bbox.zmax:.3f})")
    print(f"BBox center=({bc.x:.3f},{bc.y:.3f},{bc.z:.3f})")

    # --- Find a good "vertical" planar face to attach to ---
    # Heuristic: choose the largest-area planar face whose normal is approximately horizontal (|nz| small)
    planar_faces = []
    for f in base_shape.Faces():
        try:
            surf = f.geomType()
        except Exception:
            surf = None
        if str(surf).upper() != 'PLANE':
            continue

        # Get a representative normal and centroid
        try:
            u0, u1, v0, v1 = f._uvBounds()
            um = 0.5 * (u0 + u1)
            vm = 0.5 * (v0 + v1)
            n = f.normalAt(um, vm)
        except Exception:
            # fallback: normalAt() with no params
            try:
                n = f.normalAt()
            except Exception:
                continue

        n = Vector(n.x, n.y, n.z)
        try:
            n = n.normalized()
        except Exception:
            continue

        # vertical face => normal mostly in XY (horizontal), i.e. nz ~ 0
        if abs(n.z) > 0.2:
            continue

        area = f.Area()
        c = f.Center()
        planar_faces.append((area, f, Vector(c.x, c.y, c.z), n))

    if not planar_faces:
        raise ValueError("No suitable vertical planar faces found (planar with |nz|<=0.2).")

    planar_faces.sort(key=lambda t: t[0], reverse=True)
    area, ref_face, face_c, face_n = planar_faces[0]

    print("Chosen reference face:")
    print(f"  area={area:.3f}")
    print(f"  centroid=({face_c.x:.3f},{face_c.y:.3f},{face_c.z:.3f})")
    print(f"  normal=({face_n.x:.4f},{face_n.y:.4f},{face_n.z:.4f})")

    # --- Ring parameters (mm) ---
    outer_d = 40.0
    inner_d = 20.0
    thickness = 30.0
    R = outer_d / 2.0
    r = inner_d / 2.0

    # Slight overlap into body to avoid non-manifold tangent-only union
    overlap = 0.5  # mm

    # --- Determine which global axis the face normal is closest to (X or Y), then place ring outside ---
    # Decide outward direction based on whether face centroid lies on min-side or max-side of bbox.
    # Determine dominant normal component
    ax = abs(face_n.x)
    ay = abs(face_n.y)

    if ax >= ay:
        # plane is approximately YZ (x = const), offset along +/-X
        if face_c.x < bc.x:
            out_dir = Vector(-1, 0, 0)
        else:
            out_dir = Vector(1, 0, 0)
        # pick ring axis direction within the plane: use global Y if possible
        axis_dir = Vector(0, 1, 0)
        if abs(axis_dir.dot(out_dir)) > 0.2:
            axis_dir = Vector(0, 0, 1)  # fallback
    else:
        # plane is approximately XZ (y = const), offset along +/-Y
        if face_c.y < bc.y:
            out_dir = Vector(0, -1, 0)
        else:
            out_dir = Vector(0, 1, 0)
        # pick ring axis direction within the plane: use global X
        axis_dir = Vector(1, 0, 0)
        if abs(axis_dir.dot(out_dir)) > 0.2:
            axis_dir = Vector(0, 0, 1)  # fallback

    axis_dir = axis_dir.normalized()

    # Tangency to the plane: distance from cylinder axis to the plane should be R.
    # With overlap: use (R - overlap)
    ring_center = face_c + out_dir * (R - overlap)

    print("Ring placement:")
    print(f"  ring_center=({ring_center.x:.3f},{ring_center.y:.3f},{ring_center.z:.3f})")
    print(f"  out_dir=({out_dir.x:.1f},{out_dir.y:.1f},{out_dir.z:.1f})")
    print(f"  axis_dir=({axis_dir.x:.1f},{axis_dir.y:.1f},{axis_dir.z:.1f})")

    # --- Build annular cylinder (outer minus inner) along axis_dir, centered at ring_center ---
    base_pt = ring_center - axis_dir * (thickness / 2.0)
    outer_cyl = cq.Solid.makeCylinder(R, thickness, base_pt, axis_dir)
    inner_cyl = cq.Solid.makeCylinder(r, thickness + 2.0, base_pt - axis_dir * 1.0, axis_dir)
    ring_solid = outer_cyl.cut(inner_cyl)

    ring_wp = cq.Workplane("XY").newObject([ring_solid])

    # --- Union with base model ---
    result = base_wp.union(ring_wp)

    return result
