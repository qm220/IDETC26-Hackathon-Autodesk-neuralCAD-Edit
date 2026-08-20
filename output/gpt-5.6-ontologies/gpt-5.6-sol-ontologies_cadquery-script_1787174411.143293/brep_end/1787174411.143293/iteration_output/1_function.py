def my_cad_function(args):
    import os
    import math
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Pln, gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported

    if not source.isValid() or len(source.Solids()) != 1:
        raise ValueError("Expected one valid source solid")

    # T01: Scale only the existing component. Dimensions specified later in the
    # request remain final absolute millimetre dimensions.
    scale_transform = gp_Trsf()
    scale_transform.SetScale(gp_Pnt(0.0, 0.0, 0.0), 10.0)
    scale_op = BRepBuilderAPI_Transform(source.wrapped, scale_transform, True)
    scale_op.Build()
    edited = cq.Shape.cast(scale_op.Shape())

    bb = edited.BoundingBox()
    bottom_z = bb.zmin
    print(
        "Scaled bbox: "
        f"x=({bb.xmin:.4f},{bb.xmax:.4f}), "
        f"y=({bb.ymin:.4f},{bb.ymax:.4f}), "
        f"z=({bb.zmin:.4f},{bb.zmax:.4f})"
    )

    # T02: Draft the planar faces whose normals are perpendicular to the
    # bottom-face normal. The neutral plane is the preserved flat bottom.
    vertical_faces = []
    for face in edited.Faces():
        if face.geomType() != "PLANE":
            continue
        try:
            n = face.normalAt(face.Center())
        except Exception:
            continue
        if abs(n.z) < 1.0e-5 and face.BoundingBox().zlen > 1.0:
            vertical_faces.append(face)

    print(f"Vertical planar faces selected for draft: {len(vertical_faces)}")
    neutral_plane = gp_Pln(
        gp_Pnt(0.0, 0.0, bottom_z),
        gp_Dir(0.0, 0.0, 1.0)
    )
    pull_direction = gp_Dir(0.0, 0.0, 1.0)
    draft_angle = math.radians(2.0)

    drafted = None
    draft_error = None
    for flag in (True, False):
        try:
            draft_op = BRepOffsetAPI_DraftAngle(edited.wrapped)
            for face in vertical_faces:
                draft_op.Add(
                    face.wrapped,
                    pull_direction,
                    draft_angle,
                    neutral_plane,
                    flag
                )
            draft_op.Build()
            candidate = cq.Shape.cast(draft_op.Shape())
            if candidate.isValid() and len(candidate.Solids()) == 1:
                drafted = candidate
                print(f"2 degree draft completed with flag={flag}")
                break
        except Exception as exc:
            draft_error = exc
            print(f"Draft attempt flag={flag} failed: {exc}")

    if drafted is None:
        raise RuntimeError(f"Unable to apply requested draft: {draft_error}")
    edited = drafted

    # Edge classification after drafting. The scaled original has outer limits
    # near |X|=10 and |Y|=30, while its underside cavity lies near |X|=8 and
    # |Y|=28. Edges geometrically lying in the bottom plane are excluded.
    def lies_on_bottom(edge, z0, tol=1.0e-4):
        eb = edge.BoundingBox()
        return eb.zlen <= tol and abs(eb.zmin - z0) <= tol

    def is_cavity_edge(edge):
        eb = edge.BoundingBox()
        x_extent = max(abs(eb.xmin), abs(eb.xmax))
        y_extent = max(abs(eb.ymin), abs(eb.ymax))
        return x_extent < 9.2 and y_extent < 29.2

    # T03: Apply R1 to all non-bottom cavity/inner edges in one operation so
    # corners meeting at a common vertex are resolved together.
    inner_edges = [
        edge for edge in edited.Edges()
        if not lies_on_bottom(edge, bottom_z) and is_cavity_edge(edge)
    ]
    print(f"Inner non-bottom edges selected for R1: {len(inner_edges)}")
    if inner_edges:
        try:
            inner_result = edited.makeFillet(1.0, inner_edges)
            if inner_result.isValid():
                edited = inner_result
            else:
                raise RuntimeError("R1 result was invalid")
        except Exception as exc:
            raise RuntimeError(f"Unable to apply requested R1 inner rounds: {exc}")

    # T04: Recompute topology and round exterior edges R3. Generated edges from
    # the R1 operation remain in the cavity region and are not selected here.
    outer_edges = []
    for edge in edited.Edges():
        if lies_on_bottom(edge, bottom_z):
            continue
        eb = edge.BoundingBox()
        x_extent = max(abs(eb.xmin), abs(eb.xmax))
        y_extent = max(abs(eb.ymin), abs(eb.ymax))
        if x_extent >= 9.2 or y_extent >= 29.2:
            outer_edges.append(edge)

    print(f"Outer non-bottom edges selected for R3: {len(outer_edges)}")
    if outer_edges:
        try:
            outer_result = edited.makeFillet(3.0, outer_edges)
            if outer_result.isValid():
                edited = outer_result
            else:
                raise RuntimeError("R3 result was invalid")
        except Exception as exc:
            raise RuntimeError(f"Unable to apply requested R3 outer rounds: {exc}")

    # T05/T06 interpretation grounded in the part geometry:
    # - Pair spacing is 30 mm axis-to-axis along the long Y direction.
    # - Pair midpoint is at the main-part center (X=0, Y=0).
    # - Cylinders occupy the underside relief and rise from the bottom level to
    #   the underside of the upper cradle wall.
    # - Each D3 hole passes through its corresponding added feature and remains
    #   blind at the existing cradle wall.
    outer_radius = 3.0
    hole_radius = 1.5
    cylinder_y_positions = (-15.0, 15.0)

    # The scaled source's concentric seating-shell surfaces have center
    # Z=42.15 mm and underside radius 44.15 mm. Evaluate the underside wall at
    # the cylinder axes. A small outer overlap guarantees a robust union, while
    # cutting the ring before union leaves the existing wall intact at the end
    # of each hole.
    shell_center_z = 42.15
    underside_radius = 44.15

    for y_pos in cylinder_y_positions:
        roof_z = shell_center_z - math.sqrt(
            underside_radius * underside_radius - y_pos * y_pos
        )
        outer_height = roof_z - bottom_z + 1.0
        hole_height = roof_z - bottom_z + 0.02

        base_point = cq.Vector(0.0, y_pos, bottom_z)
        axis = cq.Vector(0.0, 0.0, 1.0)
        outer_cylinder = cq.Solid.makeCylinder(
            outer_radius, outer_height, base_point, axis
        )
        inner_cylinder = cq.Solid.makeCylinder(
            hole_radius, hole_height, base_point, axis
        )
        hollow_feature = outer_cylinder.cut(inner_cylinder)
        edited = edited.fuse(hollow_feature)

        print(
            f"Added hollow cylinder at (0,{y_pos:.3f}), "
            f"OD=6, ID=3, bottom={bottom_z:.4f}, wall={roof_z:.4f}"
        )

    # Refine boolean seams without changing the requested geometry.
    try:
        edited = edited.clean()
    except Exception:
        pass

    if not edited.isValid():
        raise RuntimeError("Final edited part is invalid")

    final_bb = edited.BoundingBox()
    print(
        f"Final solid count={len(edited.Solids())}, valid={edited.isValid()}, "
        f"bbox size=({final_bb.xlen:.4f}, {final_bb.ylen:.4f}, {final_bb.zlen:.4f})"
    )

    return cq.Workplane("XY").newObject([edited])