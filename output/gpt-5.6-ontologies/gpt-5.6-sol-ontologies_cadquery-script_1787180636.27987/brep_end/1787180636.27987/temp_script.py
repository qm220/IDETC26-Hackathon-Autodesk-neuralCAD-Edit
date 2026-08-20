def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val() if hasattr(model, "val") else model
    bbox = original.BoundingBox()

    # Identify the outermost planar +Y vertical face of the enlarged rounded base.
    # On the supplied model this is the broad face at y = 320 mm.
    candidates = []
    for face in original.Faces():
        fb = face.BoundingBox()
        try:
            is_plane = face.geomType() == "PLANE"
        except Exception:
            is_plane = False
        if (is_plane and
                abs(fb.ymax - fb.ymin) < 1.0e-5 and
                abs(fb.ymax - bbox.ymax) < 1.0e-4):
            candidates.append(face)

    if not candidates:
        raise ValueError("Could not identify the outer vertical face of the rounded base")

    target_face = max(candidates, key=lambda f: f.Area())
    target_bbox = target_face.BoundingBox()

    # Center the attachment in the two in-surface directions of the selected face.
    center_x = 0.5 * (target_bbox.xmin + target_bbox.xmax)
    center_z = 0.5 * (target_bbox.zmin + target_bbox.zmax)
    surface_y = target_bbox.ymax

    outer_radius = 20.0       # 4 cm outer diameter
    hole_radius = 10.0        # 2 cm concentric-hole diameter
    thickness = 30.0          # 3 cm axial thickness

    # Axis is X, which lies in and is therefore parallel to the vertical Y-normal face.
    axis_start_x = center_x - thickness / 2.0

    # A minimal 0.5 mm penetration produces a reliable, structurally connected union
    # while retaining the intended nominal tangential placement against y=surface_y.
    integration_overlap = 0.5
    ring_center_y = surface_y + outer_radius - integration_overlap

    outer = cq.Solid.makeCylinder(
        outer_radius,
        thickness,
        cq.Vector(axis_start_x, ring_center_y, center_z),
        cq.Vector(1, 0, 0)
    )
    inner = cq.Solid.makeCylinder(
        hole_radius,
        thickness + 2.0,
        cq.Vector(axis_start_x - 1.0, ring_center_y, center_z),
        cq.Vector(1, 0, 0)
    )
    annular_attachment = outer.cut(inner)

    edited = original.fuse(annular_attachment).clean()
    if not edited.isValid():
        raise ValueError("Edited model is not a valid B-rep")

    eb = edited.BoundingBox()
    ideal_ring_volume = math.pi * (outer_radius**2 - hole_radius**2) * thickness
    print("TARGET FACE BBOX: x=[%.4f, %.4f], y=%.4f, z=[%.4f, %.4f]" % (
        target_bbox.xmin, target_bbox.xmax, surface_y,
        target_bbox.zmin, target_bbox.zmax))
    print("ATTACHMENT CENTER: (%.4f, %.4f, %.4f)" % (
        center_x, ring_center_y, center_z))
    print("ATTACHMENT AXIS: (1, 0, 0), parallel to target face")
    print("OUTER DIAMETER: %.4f mm" % (2.0 * outer_radius))
    print("HOLE DIAMETER: %.4f mm" % (2.0 * hole_radius))
    print("THICKNESS: %.4f mm" % thickness)
    print("IDEAL ANNULAR VOLUME: %.6f mm^3" % ideal_ring_volume)
    print("EDITED MODEL VALID:", edited.isValid())
    print("EDITED MODEL VOLUME: %.6f mm^3" % edited.Volume())
    print("EDITED BBOX: x=[%.4f, %.4f], y=[%.4f, %.4f], z=[%.4f, %.4f]" % (
        eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax))

    return cq.Workplane("XY").newObject([edited])