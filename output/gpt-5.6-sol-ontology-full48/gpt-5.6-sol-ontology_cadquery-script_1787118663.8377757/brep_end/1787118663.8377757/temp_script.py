def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported

    print("SOURCE MODEL INSPECTION")
    print("valid=", source.isValid(), "solids=", len(source.Solids()), "faces=", len(source.Faces()))
    for i, face in enumerate(source.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = face.normalAt(c)
            nt = (n.x, n.y, n.z)
        except Exception:
            nt = None
        print("FACE", i, gt, "center", (c.x, c.y, c.z), "normal", nt,
              "bbox", (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    # 1. Uniformly scale the complete part about its symmetry origin.
    shape = source.scale(10.0)
    scaled_bb = shape.BoundingBox()
    bottom_z = scaled_bb.zmin
    print("SCALED BBOX", (scaled_bb.xmin, scaled_bb.xmax,
                           scaled_bb.ymin, scaled_bb.ymax,
                           scaled_bb.zmin, scaled_bb.zmax))

    # 2. Draft all planar vertical walls by 2 degrees, with the original
    # flat bottom plane used as the neutral/hinge plane.
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
        from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

        builder = BRepOffsetAPI_DraftAngle(shape.wrapped)
        pull = gp_Dir(0.0, 0.0, 1.0)
        neutral = gp_Pln(gp_Pnt(0.0, 0.0, bottom_z), pull)
        draft_faces = []

        for face in shape.Faces():
            if face.geomType() != "PLANE":
                continue
            c = face.Center()
            n = face.normalAt(c)
            if abs(n.z) < 1.0e-6:
                draft_faces.append(face)

        print("VERTICAL FACES SELECTED FOR DRAFT", len(draft_faces))
        for face in draft_faces:
            builder.Add(face.wrapped, pull, math.radians(2.0), neutral, True)

        builder.Build()
        if builder.IsDone():
            candidate = cq.Shape.cast(builder.Shape())
            if candidate.isValid() and len(candidate.Solids()) == 1:
                shape = candidate
                print("DRAFT SUCCEEDED")
            else:
                print("DRAFT RESULT INVALID; RETAINING SCALED BODY")
        else:
            print("DRAFT BUILDER NOT DONE; RETAINING SCALED BODY")
    except Exception as exc:
        print("DRAFT FAILED", repr(exc))

    def is_bottom_edge(edge, tol=1.0e-5):
        eb = edge.BoundingBox()
        return abs(eb.zmin-bottom_z) < tol and abs(eb.zmax-bottom_z) < tol

    def signature(edge):
        c = edge.Center()
        return (c.x, c.y, c.z, edge.Length())

    def closest_edge(body, sig, predicate=None):
        sx, sy, sz, sl = sig
        choices = []
        for edge in body.Edges():
            if is_bottom_edge(edge):
                continue
            if predicate is not None and not predicate(edge, body):
                continue
            c = edge.Center()
            score = ((c.x-sx)**2 + (c.y-sy)**2 + (c.z-sz)**2 +
                     0.03*(edge.Length()-sl)**2)
            choices.append((score, edge))
        return min(choices, key=lambda item: item[0])[1] if choices else None

    # The four exterior corner edges run upward from the four corners of the
    # bottom footprint. They are selected from the drafted topology rather
    # than relying on the original STEP face indices.
    def outer_corner_predicate(edge, body):
        if is_bottom_edge(edge):
            return False
        eb = edge.BoundingBox()
        bb = body.BoundingBox()
        tol = 1.0e-4
        starts_at_bottom = abs(eb.zmin-bottom_z) < tol
        has_height = eb.zmax-eb.zmin > 5.0
        touches_x_side = abs(eb.xmin-bb.xmin) < tol or abs(eb.xmax-bb.xmax) < tol
        touches_y_end = abs(eb.ymin-bb.ymin) < tol or abs(eb.ymax-bb.ymax) < tol
        return starts_at_bottom and has_height and touches_x_side and touches_y_end

    # Interior edges do not touch the outside XY limits. This captures the
    # cavity, shell-underside, and inner rail transitions while excluding all
    # edges lying wholly on the flat bottom surface.
    def inner_predicate(edge, body):
        if is_bottom_edge(edge):
            return False
        eb = edge.BoundingBox()
        bb = body.BoundingBox()
        tol = 1.0e-4
        touches_outer = (
            abs(eb.xmin-bb.xmin) < tol or abs(eb.xmax-bb.xmax) < tol or
            abs(eb.ymin-bb.ymin) < tol or abs(eb.ymax-bb.ymax) < tol
        )
        return not touches_outer

    def apply_fillet(body, edges, radius, label, rebinding_predicate=None):
        print(label, "INITIAL EDGE COUNT", len(edges), "RADIUS", radius)
        for edge in edges:
            c = edge.Center()
            eb = edge.BoundingBox()
            print(label, "EDGE", (c.x, c.y, c.z), "LENGTH", edge.Length(),
                  "BBOX", (eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax))
        if not edges:
            return body

        try:
            candidate = body.fillet(radius, edges)
            if candidate.isValid() and len(candidate.Solids()) == 1:
                print(label, "BATCH FILLET SUCCEEDED")
                return candidate
        except Exception as exc:
            print(label, "BATCH FILLET FAILED", repr(exc))

        result = body
        successes = 0
        for sig in [signature(e) for e in edges]:
            edge = closest_edge(result, sig, rebinding_predicate)
            if edge is None:
                continue
            try:
                candidate = result.fillet(radius, [edge])
                if candidate.isValid() and len(candidate.Solids()) == 1:
                    result = candidate
                    successes += 1
            except Exception as exc:
                print(label, "INDIVIDUAL EDGE FAILED", repr(exc))
        print(label, "INDIVIDUAL FILLET SUCCESSES", successes)
        return result

    # 3/4. Apply exterior R3 rounds before the interior R1 rounds. In the
    # previous result the interior fillet was performed first and consumed
    # the available corner topology, causing every requested R3 operation to
    # fail. Bottom-plane edges remain excluded from both operations.
    outer_edges = [e for e in shape.Edges() if outer_corner_predicate(e, shape)]
    shape = apply_fillet(shape, outer_edges, 3.0, "OUTER", outer_corner_predicate)

    inner_edges = [e for e in shape.Edges() if inner_predicate(e, shape)]
    shape = apply_fillet(shape, inner_edges, 1.0, "INNER", inner_predicate)

    # 5. Add two D6 vertical cylindrical features centered about the part.
    # Their centers are at y +/-15 mm, hence their center spacing is 30 mm.
    # They begin at the flat-bottom level and are trimmed against the scaled
    # concave top-side wall.
    boss_radius = 3.0
    hole_radius = 1.5
    boss_centers = [(0.0, -15.0), (0.0, 15.0)]
    top_z = shape.BoundingBox().zmax
    boss_height = top_z-bottom_z+3.0

    # Grounded from FACE 7: after scaling, the seating cylinder has radius
    # 42.15 mm, axis parallel to X, and center z=42.15 mm.
    seat_radius = 42.15
    trim_length = 50.0
    seat_trim = cq.Solid.makeCylinder(
        seat_radius,
        trim_length,
        cq.Vector(-trim_length/2.0, 0.0, seat_radius),
        cq.Vector(1.0, 0.0, 0.0)
    )

    for x, y in boss_centers:
        outer = cq.Solid.makeCylinder(
            boss_radius,
            boss_height,
            cq.Vector(x, y, bottom_z),
            cq.Vector(0.0, 0.0, 1.0)
        )
        boss = outer.cut(seat_trim)
        shape = shape.fuse(boss)
        print("BOSS CENTER", (x, y), "START", bottom_z)

    # 6. Cut one coaxial D3 hole through each new cylindrical feature.
    hole_depth = shape.BoundingBox().zmax-bottom_z+6.0
    for x, y in boss_centers:
        hole = cq.Solid.makeCylinder(
            hole_radius,
            hole_depth,
            cq.Vector(x, y, bottom_z-3.0),
            cq.Vector(0.0, 0.0, 1.0)
        )
        shape = shape.cut(hole)

    try:
        shape = shape.clean()
    except Exception as exc:
        print("CLEAN FAILED", repr(exc))

    final_bb = shape.BoundingBox()
    print("FINAL MODEL")
    print("valid=", shape.isValid(), "solids=", len(shape.Solids()),
          "faces=", len(shape.Faces()), "edges=", len(shape.Edges()))
    print("bbox=", (final_bb.xmin, final_bb.xmax, final_bb.ymin,
                     final_bb.ymax, final_bb.zmin, final_bb.zmax))
    print("boss spacing=30.0, OD=6.0, hole diameter=3.0")

    return cq.Workplane("XY").newObject([shape])