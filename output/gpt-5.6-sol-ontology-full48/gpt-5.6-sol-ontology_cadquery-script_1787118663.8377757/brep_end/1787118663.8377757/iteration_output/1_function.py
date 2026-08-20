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

    # 1. Uniformly scale the complete source solid about its symmetry origin.
    shape = source.scale(10.0)
    bb = shape.BoundingBox()
    bottom_z = bb.zmin
    print("SCALED BBOX", (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    # 2. Draft every planar vertical face by two degrees, using the bottom
    # plane as the neutral/hinge plane and +Z as the pull direction.
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
        from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

        draft_builder = BRepOffsetAPI_DraftAngle(shape.wrapped)
        pull = gp_Dir(0.0, 0.0, 1.0)
        neutral = gp_Pln(gp_Pnt(0.0, 0.0, bottom_z), pull)
        draft_faces = []

        for face in shape.Faces():
            if face.geomType() != "PLANE":
                continue
            c = face.Center()
            n = face.normalAt(c)
            # A vertical face has a substantially horizontal normal.
            if abs(n.z) < 1.0e-5:
                draft_faces.append(face)

        print("VERTICAL FACES SELECTED FOR DRAFT", len(draft_faces))
        for face in draft_faces:
            draft_builder.Add(face.wrapped, pull, math.radians(2.0), neutral, True)

        draft_builder.Build()
        if draft_builder.IsDone():
            drafted = cq.Shape.cast(draft_builder.Shape())
            if drafted.isValid() and len(drafted.Solids()) == 1:
                shape = drafted
                print("DRAFT SUCCEEDED")
            else:
                print("DRAFT RESULT INVALID; retaining scaled body")
        else:
            print("DRAFT BUILDER DID NOT COMPLETE; retaining scaled body")
    except Exception as exc:
        print("DRAFT FAILED", repr(exc))

    def is_bottom_edge(edge, z0, tol=1.0e-5):
        ebb = edge.BoundingBox()
        return abs(ebb.zmin - z0) < tol and abs(ebb.zmax - z0) < tol

    def edge_signature(edge):
        c = edge.Center()
        return (c.x, c.y, c.z, edge.Length())

    def closest_edge(current_shape, signature, predicate):
        sx, sy, sz, sl = signature
        choices = []
        for edge in current_shape.Edges():
            if not predicate(edge, current_shape):
                continue
            c = edge.Center()
            score = ((c.x-sx)**2 + (c.y-sy)**2 + (c.z-sz)**2) + 0.05*(edge.Length()-sl)**2
            choices.append((score, edge))
        return min(choices, key=lambda item: item[0])[1] if choices else None

    def inner_predicate(edge, body):
        b = body.BoundingBox()
        if is_bottom_edge(edge, bottom_z):
            return False
        eb = edge.BoundingBox()
        tol = 1.0e-4
        touches_outer = (
            abs(eb.xmin-b.xmin) < tol or abs(eb.xmax-b.xmax) < tol or
            abs(eb.ymin-b.ymin) < tol or abs(eb.ymax-b.ymax) < tol
        )
        return not touches_outer

    def outer_predicate(edge, body):
        b = body.BoundingBox()
        if is_bottom_edge(edge, bottom_z):
            return False
        eb = edge.BoundingBox()
        tol = 1.0e-4
        return (
            abs(eb.xmin-b.xmin) < tol or abs(eb.xmax-b.xmax) < tol or
            abs(eb.ymin-b.ymin) < tol or abs(eb.ymax-b.ymax) < tol
        )

    def apply_fillet_group(body, radius, predicate, label):
        initial = [e for e in body.Edges() if predicate(e, body)]
        print(label, "INITIAL EDGE COUNT", len(initial), "RADIUS", radius)
        if not initial:
            return body

        # Prefer one coherent fillet operation so intersecting corners are
        # solved together by OpenCascade.
        try:
            result = body.fillet(radius, initial)
            if result.isValid():
                print(label, "BATCH FILLET SUCCEEDED")
                return result
        except Exception as exc:
            print(label, "BATCH FILLET FAILED", repr(exc))

        # Fall back to independent operations. Rebind each original edge to
        # current topology after every successful round.
        result = body
        successes = 0
        for sig in [edge_signature(e) for e in initial]:
            edge = closest_edge(result, sig, predicate)
            if edge is None:
                continue
            try:
                candidate = result.fillet(radius, [edge])
                if candidate.isValid():
                    result = candidate
                    successes += 1
            except Exception:
                pass
        print(label, "INDIVIDUAL FILLET SUCCESSES", successes)
        return result

    # 3. Inner rounds first. Bottom-plane edges are explicitly excluded.
    shape = apply_fillet_group(shape, 1.0, inner_predicate, "INNER")

    # 4. Outer rounds second. Bottom-plane edges are explicitly excluded.
    shape = apply_fillet_group(shape, 3.0, outer_predicate, "OUTER")

    # 5. Add two vertical cylindrical bosses. Their axes are centered on
    # x=0 and symmetrically placed at y=+/-15, giving 30 mm center spacing.
    # Each starts at the original flat-bottom level. Its upper end is trimmed
    # by the original concave top seating cylinder so it reaches the top-side
    # wall without protruding through that wall.
    boss_radius = 3.0
    hole_radius = 1.5
    boss_centers = [(0.0, -15.0), (0.0, 15.0)]
    top_z = shape.BoundingBox().zmax
    boss_height = top_z - bottom_z + 2.0

    # The scaled seating surface is a radius-42.15 cylinder about the X axis,
    # centered at z=42.15. Its solid interior is the material above the lower
    # concave branch and therefore serves as the upper trimming cutter.
    seat_radius = 42.15
    seat_axis_length = 40.0
    seat_trim = cq.Solid.makeCylinder(
        seat_radius,
        seat_axis_length,
        cq.Vector(-seat_axis_length/2.0, 0.0, seat_radius),
        cq.Vector(1.0, 0.0, 0.0)
    )

    bosses = []
    for x, y in boss_centers:
        outer = cq.Solid.makeCylinder(
            boss_radius, boss_height,
            cq.Vector(x, y, bottom_z), cq.Vector(0.0, 0.0, 1.0)
        )
        trimmed = outer.cut(seat_trim)
        bosses.append(trimmed)
        print("BOSS CENTER", (x, y), "START", bottom_z)

    for boss in bosses:
        shape = shape.fuse(boss)

    # 6. Cut one coaxial through-hole in each boss. Extending cutters beyond
    # both ends guarantees that the holes remain open through the top wall.
    hole_depth = shape.BoundingBox().zmax - bottom_z + 4.0
    for x, y in boss_centers:
        hole = cq.Solid.makeCylinder(
            hole_radius, hole_depth,
            cq.Vector(x, y, bottom_z-2.0), cq.Vector(0.0, 0.0, 1.0)
        )
        shape = shape.cut(hole)

    try:
        shape = shape.clean()
    except Exception:
        pass

    final_bb = shape.BoundingBox()
    print("FINAL MODEL")
    print("valid=", shape.isValid(), "solids=", len(shape.Solids()),
          "faces=", len(shape.Faces()), "edges=", len(shape.Edges()))
    print("bbox=", (final_bb.xmin, final_bb.xmax, final_bb.ymin,
                     final_bb.ymax, final_bb.zmin, final_bb.zmax))
    print("boss spacing=30.0, OD=6.0, hole diameter=3.0")

    return cq.Workplane("XY").newObject([shape])