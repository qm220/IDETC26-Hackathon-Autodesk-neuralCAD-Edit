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
    wb = wheel.BoundingBox()
    axis_x = 0.5 * (wb.xmin + wb.xmax)
    axis_z = 0.5 * (wb.zmin + wb.zmax)

    print('=== MODEL AND FRONT-CENTER GEOMETRY DIAGNOSTIC ===')
    print('Solid count:', len(solids))
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print('SOLID %d volume=%.6f bbox=(%.6f, %.6f) (%.6f, %.6f) (%.6f, %.6f)' % (
            i, solid.Volume(), bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    print('Inferred wheel axis: X=%.6f Z=%.6f; Y range %.6f to %.6f' % (
        axis_x, axis_z, wb.ymin, wb.ymax))

    # Report all axis-centered circular edges around the hub. This avoids
    # assuming that the wheel's tooth bounding-box maximum is also the hub's
    # front plane.
    circles = []
    seen = set()
    for index, edge in enumerate(wheel.Edges()):
        try:
            key = edge.hashCode()
            if key in seen:
                continue
            seen.add(key)
            if edge.geomType() != 'CIRCLE':
                continue
            bb = edge.BoundingBox()
            center = edge.Center()
            rx = 0.5 * (bb.xmax - bb.xmin)
            rz = 0.5 * (bb.zmax - bb.zmin)
            radius = max(rx, rz)
            offset = math.hypot(center.x - axis_x, center.z - axis_z)
            if offset < 0.2 and radius < 40.0:
                circles.append((center.y, radius, index, bb, edge.Length()))
        except Exception:
            pass

    circles.sort(key=lambda item: (-item[0], item[1]))
    print('Axis-centered circular wheel edges (Y, radius, edge-index, length):')
    for y, radius, index, bb, length in circles:
        print('  Y=% .6f R=% .6f EDGE=%d L=%.6f bboxY=(%.6f,%.6f)' % (
            y, radius, index, length, bb.ymin, bb.ymax))

    # Report front/back-facing planar faces near the wheel center and their
    # radial spans. These data identify the planar front hub annulus directly.
    print('Planar wheel faces normal to the Y axis and within hub radius:')
    for index, face in enumerate(wheel.Faces()):
        try:
            if face.geomType() != 'PLANE':
                continue
            center = face.Center()
            normal = face.normalAt(center)
            if abs(normal.y) < 0.90:
                continue
            bb = face.BoundingBox()
            radial_extent = max(
                abs(bb.xmin - axis_x), abs(bb.xmax - axis_x),
                abs(bb.zmin - axis_z), abs(bb.zmax - axis_z))
            radial_center = math.hypot(center.x - axis_x, center.z - axis_z)
            if radial_extent < 45.0 or radial_center < 25.0:
                print('  FACE=%d Y=% .6f normalY=% .3f area=%.6f centerR=%.6f extentR=%.6f type=%s' % (
                    index, center.y, normal.y, face.Area(), radial_center,
                    radial_extent, face.geomType()))
        except Exception:
            pass

    print('Non-planar faces centered near the hub:')
    for index, face in enumerate(wheel.Faces()):
        try:
            center = face.Center()
            radial_center = math.hypot(center.x - axis_x, center.z - axis_z)
            bb = face.BoundingBox()
            radial_extent = max(
                abs(bb.xmin - axis_x), abs(bb.xmax - axis_x),
                abs(bb.zmin - axis_z), abs(bb.zmax - axis_z))
            if radial_center < 25.0 and radial_extent < 40.0 and face.geomType() != 'PLANE':
                print('  FACE=%d type=%s center=(%.6f,%.6f,%.6f) area=%.6f extentR=%.6f' % (
                    index, face.geomType(), center.x, center.y, center.z,
                    face.Area(), radial_extent))
        except Exception:
            pass

    # Diagnostic iteration only: preserve and return the unmodified source
    # model so the printed topology can be used to target the requested edit.
    result = cq.Compound.makeCompound(solids) if len(solids) > 1 else solids[0]
    return cq.Workplane('XY').newObject([result])