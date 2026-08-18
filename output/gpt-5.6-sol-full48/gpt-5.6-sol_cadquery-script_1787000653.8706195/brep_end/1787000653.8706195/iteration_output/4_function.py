def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root = imported.val()
    solids = list(root.Solids())
    if not solids:
        raise RuntimeError('No solids were imported from the STEP file')

    solids.sort(key=lambda s: s.Volume(), reverse=True)
    wheel = solids[0]
    faces = list(wheel.Faces())
    wb = wheel.BoundingBox()
    axis_x = 0.5 * (wb.xmin + wb.xmax)
    axis_z = 0.5 * (wb.zmin + wb.zmax)

    def radial_bounds(bb):
        corners = [
            (bb.xmin, bb.zmin), (bb.xmin, bb.zmax),
            (bb.xmax, bb.zmin), (bb.xmax, bb.zmax)
        ]
        rmax = max(math.hypot(x-axis_x, z-axis_z) for x, z in corners)
        dx = 0.0 if bb.xmin <= axis_x <= bb.xmax else min(abs(bb.xmin-axis_x), abs(bb.xmax-axis_x))
        dz = 0.0 if bb.zmin <= axis_z <= bb.zmax else min(abs(bb.zmin-axis_z), abs(bb.zmax-axis_z))
        return math.hypot(dx, dz), rmax

    def radius(p):
        return math.hypot(p.x-axis_x, p.z-axis_z)

    def adjacent_face_indices(face_index):
        result = set()
        target_edges = list(faces[face_index].Edges())
        for j, other in enumerate(faces):
            if j == face_index:
                continue
            for e1 in target_edges:
                matched = False
                for e2 in other.Edges():
                    try:
                        if e1.isSame(e2):
                            result.add(j)
                            matched = True
                            break
                    except Exception:
                        pass
                if matched:
                    break
        return sorted(result)

    print('=== CENTRAL HUB EDGE-TREATMENT DIAGNOSTIC ===')
    print('Wheel faces:', len(faces))
    print('Wheel bbox: X=(%.6f, %.6f), Y=(%.6f, %.6f), Z=(%.6f, %.6f)' % (
        wb.xmin, wb.xmax, wb.ymin, wb.ymax, wb.zmin, wb.zmax))
    print('Rotation axis: X=%.6f, Z=%.6f' % (axis_x, axis_z))

    # List all curved faces confined to the central hub. This distinguishes
    # the requested outer front hub fillet from the insert-entry chamfers,
    # rear hub blend, and spoke-root blends.
    candidates = []
    for i, face in enumerate(faces):
        bb = face.BoundingBox()
        rmin, rmax = radial_bounds(bb)
        gt = face.geomType()
        if rmax <= 26.0 and gt in ('TORUS', 'CONE', 'CYLINDER', 'SPHERE'):
            candidates.append(i)

    for i in candidates:
        face = faces[i]
        bb = face.BoundingBox()
        c = face.Center()
        rmin, rmax = radial_bounds(bb)
        print('\nCANDIDATE local=%d inferredGlobal=%d type=%s area=%.6f' % (
            i, i + 234, face.geomType(), face.Area()))
        print(' center=(%.6f, %.6f, %.6f), centerR=%.6f' % (
            c.x, c.y, c.z, radius(c)))
        print(' bboxY=(%.6f, %.6f), radialBBox=(%.6f, %.6f)' % (
            bb.ymin, bb.ymax, rmin, rmax))
        print(' adjacent:', adjacent_face_indices(i))
        for k, edge in enumerate(face.Edges()):
            eb = edge.BoundingBox()
            ec = edge.Center()
            ermin, ermax = radial_bounds(eb)
            verts = []
            for vertex in edge.Vertices():
                p = vertex.Center()
                verts.append('(y=%.6f,r=%.6f)' % (p.y, radius(p)))
            print('  edge=%d type=%s length=%.6f centerY=%.6f centerR=%.6f bboxY=(%.6f,%.6f) radialBBox=(%.6f,%.6f) vertices=%s' % (
                k, edge.geomType(), edge.Length(), ec.y, radius(ec),
                eb.ymin, eb.ymax, ermin, ermax, ','.join(verts)))

    # Also report planar annular hub faces and their circular boundaries.
    print('\n=== CENTRAL PLANAR FACES ===')
    for i, face in enumerate(faces):
        if face.geomType() != 'PLANE':
            continue
        bb = face.BoundingBox()
        rmin, rmax = radial_bounds(bb)
        if rmax > 26.0 or face.Area() < 10.0:
            continue
        circular = [e for e in face.Edges() if e.geomType() == 'CIRCLE']
        if not circular:
            continue
        c = face.Center()
        print('PLANAR local=%d inferredGlobal=%d area=%.6f centerY=%.6f radialBBox=(%.6f,%.6f) adjacent=%s' % (
            i, i + 234, face.Area(), c.y, rmin, rmax, adjacent_face_indices(i)))
        for k, edge in enumerate(circular):
            eb = edge.BoundingBox()
            ec = edge.Center()
            ermin, ermax = radial_bounds(eb)
            print('  circle=%d length=%.6f centerY=%.6f radialBBox=(%.6f,%.6f)' % (
                k, edge.Length(), ec.y, ermin, ermax))

    # This pass intentionally preserves the source while locating the exact
    # annular fillet. The next pass will replace only that face with a 1 mm
    # equal-distance chamfer and retain the two separate solids.
    result = cq.Compound.makeCompound(solids) if len(solids) > 1 else solids[0]
    return cq.Workplane('XY').newObject([result])