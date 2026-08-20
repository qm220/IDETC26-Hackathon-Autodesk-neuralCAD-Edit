def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # The existing upper axial connection boss is centered at
    # X=67.5, Z=-21 and terminates at the semantic top plane Y=180.
    # Mount the fixation rod into this boss and project it 200 mm in +Y.
    axis_x = 67.5
    axis_z = -21.0
    mounting_y = 180.0
    arm_length = 200.0
    distal_y = mounting_y + arm_length
    axis = cq.Vector(0, 1, 0)

    # Inserted stem uses the existing axial connection hole.
    stem = cq.Solid.makeCylinder(
        6.5,
        23.0,
        cq.Vector(axis_x, 165.0, axis_z),
        axis
    )

    # A mounting collar overlaps the annular upper boss to form a robust,
    # single-solid top attachment and provides a positive seating shoulder.
    collar = cq.Solid.makeCylinder(
        10.0,
        11.0,
        cq.Vector(axis_x, 177.0, axis_z),
        axis
    )

    # Blended-size shoulder from the mounting collar to the fixation arm.
    shoulder = cq.Solid.makeCone(
        10.0,
        6.5,
        8.0,
        cq.Vector(axis_x, 185.0, axis_z),
        axis
    )

    # The requested arm reach is exactly 200 mm from Y=180 to Y=380.
    # It terminates short of the endpoint so the contact pad remains within
    # the specified total arm envelope.
    arm = cq.Solid.makeCylinder(
        6.5,
        192.0,
        cq.Vector(axis_x, mounting_y, axis_z),
        axis
    )

    # Enlarged distal pressure/contact pad for engaging and constraining the
    # cutting product. Its outer contact face is exactly 200 mm from the mount.
    contact_pad = cq.Solid.makeCylinder(
        18.0,
        8.0,
        cq.Vector(axis_x, distal_y - 8.0, axis_z),
        axis
    )

    fixation_feature = stem.fuse(collar)
    fixation_feature = fixation_feature.fuse(shoulder)
    fixation_feature = fixation_feature.fuse(arm)
    fixation_feature = fixation_feature.fuse(contact_pad)

    edited = original.fuse(fixation_feature).clean()
    result = cq.Workplane("XY").newObject([edited])

    bbox = edited.BoundingBox()
    print("EDITED MODEL VALID:", edited.isValid())
    print("SOLID COUNT:", len(edited.Solids()))
    print("MODEL BBOX:",
          (bbox.xmin, bbox.ymin, bbox.zmin),
          (bbox.xmax, bbox.ymax, bbox.zmax))
    print("FIXATION ROD MOUNT Y:", mounting_y)
    print("FIXATION ROD DISTAL Y:", distal_y)
    print("FIXATION ARM LENGTH:", distal_y - mounting_y, "mm")

    return result