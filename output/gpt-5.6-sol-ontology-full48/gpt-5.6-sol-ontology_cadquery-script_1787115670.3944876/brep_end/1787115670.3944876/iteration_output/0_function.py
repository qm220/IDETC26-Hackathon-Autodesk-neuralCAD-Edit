def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    # Inspect the grounded STEP faces before editing. FACE N corresponds to this
    # global Faces() ordering from the imported shape.
    faces = model.Faces()
    print("Loaded STEP:", input_file)
    print("Model valid:", model.isValid())
    print("Solids:", len(model.Solids()), "Faces:", len(faces))
    bb = model.BoundingBox()
    print("Model bbox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    for idx in (22, 46, 794, 795, 796, 797, 798):
        if idx < len(faces):
            face = faces[idx]
            fb = face.BoundingBox()
            c = face.Center()
            try:
                kind = face.geomType()
            except Exception:
                kind = "UNKNOWN"
            print("FACE %d: type=%s center=(%.3f, %.3f, %.3f) bbox=x(%.3f,%.3f) y(%.3f,%.3f) z(%.3f,%.3f)" %
                  (idx, kind, c.x, c.y, c.z, fb.xmin, fb.xmax,
                   fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    # Find front-facing planar perimeter candidates near the two mirrored
    # corner locations. This verifies the host geometry rather than relying
    # solely on the planning-stage face numbering.
    target_yz = [(152.4, -231.14), (-152.4, 233.68)]
    for i, face in enumerate(faces):
        try:
            if face.geomType() != "PLANE":
                continue
            fb = face.BoundingBox()
            c = face.Center()
            thin_x = (fb.xmax - fb.xmin) < 0.2
            near_target = any(
                fb.ymin - 2.0 <= ty <= fb.ymax + 2.0 and
                fb.zmin - 2.0 <= tz <= fb.zmax + 2.0
                for ty, tz in target_yz
            )
            if thin_x and near_target:
                print("Candidate front tank FACE %d: x=%.3f center=(%.3f,%.3f,%.3f) y-span=(%.3f,%.3f) z-span=(%.3f,%.3f)" %
                      (i, 0.5 * (fb.xmin + fb.xmax), c.x, c.y, c.z,
                       fb.ymin, fb.ymax, fb.zmin, fb.zmax))
        except Exception:
            pass

    # FACE 0 establishes the broad front core plane at x=-69.85. The requested
    # locations lie outside that face's y extent and on the adjacent perimeter
    # tank. Use the same front datum for the roots and project toward CAD +X.
    host_front_x = -69.85

    # Mirrored corner locations from F024/F025 as specified by operation.json.
    outlet_center = (152.4, -231.14)   # semantic top-right: +Y, -Z
    inlet_center = (-152.4, 233.68)    # semantic bottom-left: -Y, +Z

    # Compatible unresolved hydraulic standard: 12 mm clear bore, 22 mm tube
    # body, 25 mm retention barbs, and a 30 mm root flange. Both ports use the
    # same dimensions to form a compatible inlet/outlet circuit.
    bore_r = 6.0
    neck_r = 11.0
    barb_r = 12.5
    flange_r = 15.0

    def make_port(y, z, name):
        axis = cq.Vector(1, 0, 0)

        # The flange straddles the imported front tank datum, providing physical
        # attachment overlap even when invalid imported topology prevents fusion.
        flange = cq.Solid.makeCylinder(
            flange_r, 5.0, cq.Vector(host_front_x - 2.15, y, z), axis
        )
        root_transition = cq.Solid.makeCone(
            flange_r, neck_r, 5.0,
            cq.Vector(host_front_x + 2.85, y, z), axis
        )
        neck = cq.Solid.makeCylinder(
            neck_r, 32.0, cq.Vector(host_front_x + 1.0, y, z), axis
        )

        # Two hose-retention beads near the projecting end.
        barb1 = cq.Solid.makeCylinder(
            barb_r, 3.0, cq.Vector(host_front_x + 18.0, y, z), axis
        )
        barb2 = cq.Solid.makeCylinder(
            barb_r, 3.0, cq.Vector(host_front_x + 26.0, y, z), axis
        )

        body = flange.fuse(root_transition).fuse(neck).fuse(barb1).fuse(barb2)

        # Continuous coolant passage through the complete boss and slightly
        # behind the front tank datum.
        bore = cq.Solid.makeCylinder(
            bore_r, 40.0, cq.Vector(host_front_x - 5.0, y, z), axis
        )
        body = body.cut(bore)

        # Lead-in countersink/chamfer at the exposed opening.
        front_x = host_front_x + 33.0
        lead = cq.Solid.makeCone(
            bore_r + 2.0, bore_r, 3.0,
            cq.Vector(front_x, y, z), cq.Vector(-1, 0, 0)
        )
        body = body.cut(lead)
        print("Created %s at (x=%.3f, y=%.3f, z=%.3f), OD=%.1f, bore=%.1f" %
              (name, host_front_x, y, z, 2.0 * neck_r, 2.0 * bore_r))
        return body

    outlet = make_port(outlet_center[0], outlet_center[1], "top-right outlet")
    inlet = make_port(inlet_center[0], inlet_center[1], "bottom-left inlet")

    # Open each passage through the local front wall. Limit the cut to a short
    # depth so it enters the perimeter tank without traversing the radiator core.
    edited_model = model
    try:
        local_cutters = []
        for y, z in (outlet_center, inlet_center):
            local_cutters.append(cq.Solid.makeCylinder(
                bore_r, 12.0,
                cq.Vector(host_front_x - 7.0, y, z),
                cq.Vector(1, 0, 0)
            ))
        candidate = edited_model.cut(local_cutters[0]).cut(local_cutters[1])
        if not candidate.isNull() and len(candidate.Solids()) > 0:
            edited_model = candidate
            print("Local tank-wall passage cuts completed; resulting solids:",
                  len(edited_model.Solids()), "valid:", edited_model.isValid())
        else:
            print("Tank-wall cut returned an empty shape; retaining imported host.")
    except Exception as exc:
        # The source STEP is reported invalid. In that case the operation plan
        # explicitly permits deliberately separate service-interface solids.
        print("Imported-host boolean cut was not reliable:", repr(exc))
        print("Retaining hollow ports as separate service-interface solids.")
        edited_model = model

    # Preserve all imported assembly solids and add the two deliberately modeled
    # service-interface solids. Nested compounds are valid for STEP export and
    # avoid destructive fusion across the source model's invalid topology.
    result = cq.Compound.makeCompound([edited_model, outlet, inlet])
    rbb = result.BoundingBox()
    print("Result solids:", len(result.Solids()), "faces:", len(result.Faces()))
    print("Result bbox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (rbb.xmin, rbb.xmax, rbb.ymin, rbb.ymax, rbb.zmin, rbb.zmax))
    return result