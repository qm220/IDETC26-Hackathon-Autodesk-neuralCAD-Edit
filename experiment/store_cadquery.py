#!/usr/bin/env python3
"""Restore the sharp hub corner, then apply a 1 mm equal-distance chamfer.

    uv run python experiment/run_cadquery.py \\
      --input path/to/model.step \\
      --code experiment/store_cadquery.py \\
      --output experiment/cq_out
"""

import math
import os
import statistics

import cadquery as cq


def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== FILLET TO CHAMFER EDIT V3 ===")
    print(f"Original valid: {shape.isValid()}")
    print(f"Original volume: {shape.Volume():.6f}")

    # ------------------------------------------------------------------
    # 1. Locate the actual front-center hub fillet.
    # Previous topology inspection established that it is the large,
    # axis-centered toroidal face on the negative-Y side. Re-resolve it
    # geometrically so the procedure does not depend on OCC face numbers.
    # ------------------------------------------------------------------
    target_candidates = []
    for i, f in enumerate(shape.Faces()):
        try:
            if f.geomType().upper() != "TORUS":
                continue
        except Exception:
            continue

        fc = f.Center()
        fbb = f.BoundingBox()

        # Large annular hub fillet: nearly centered in X/Z, large area,
        # situated on the negative-Y/front face.
        axis_offset = math.hypot(fc.x, fc.z)
        if axis_offset < 0.5 and fc.y < -3.5 and f.Area() > 100.0:
            target_candidates.append((f.Area(), i, f))

    if not target_candidates:
        raise RuntimeError("Could not resolve the front-center hub fillet")

    target_candidates.sort(reverse=True, key=lambda x: x[0])
    _, fillet_index, fillet_face = target_candidates[0]
    print(f"Target fillet OCC face: {fillet_index}, area={fillet_face.Area():.6f}")

    # ------------------------------------------------------------------
    # 2. Resolve the two principal circular boundaries of that torus.
    # Diagnostic topology from the preceding iteration showed approximately
    # front planar tangent: Y=-4.6253, R=14.90
    # cone tangent: Y=-4.2620, R=16.78
    # We derive these values again directly from the selected face.
    # ------------------------------------------------------------------
    circle_edges = []
    for e in fillet_face.Edges():
        try:
            if e.geomType().upper() != "CIRCLE":
                continue
        except Exception:
            continue

        L = e.Length()
        ec = e.Center()
        if L > 20.0:
            r = L / (2.0 * math.pi)
            circle_edges.append((ec.y, r, e, ec))
            print(f"Fillet boundary circle: Y={ec.y:.6f}, R={r:.6f}, L={L:.6f}")

    if len(circle_edges) < 2:
        raise RuntimeError(
            "Could not identify both annular boundaries of front-center fillet"
        )

    circle_edges.sort(key=lambda t: t[0])
    front_y, r_front_tangent, front_edge, front_ec = circle_edges[0]
    cone_tangent_y, r_cone_tangent, cone_edge, cone_ec = circle_edges[-1]

    # The rotational axis is obtained from the actual circular feature,
    # NOT from the overall bounding-box center. The latter is slightly
    # offset because the surrounding wheel geometry is not perfectly
    # bounding-box symmetric.
    axis_x = 0.5 * (front_ec.x + cone_ec.x)
    axis_z = 0.5 * (front_ec.z + cone_ec.z)

    print(f"Resolved hub axis X/Z = ({axis_x:.6f}, {axis_z:.6f})")
    print(f"Front tangent = (R={r_front_tangent:.6f}, Y={front_y:.6f})")
    print(f"Cone tangent = (R={r_cone_tangent:.6f}, Y={cone_tangent_y:.6f})")

    # ------------------------------------------------------------------
    # 3. Find the parent conical hub-to-web surface adjoining the torus.
    # It is the large axis-centered cone whose lower Y boundary coincides
    # with the torus/cone tangent circle.
    # ------------------------------------------------------------------
    cone_candidates = []
    for i, f in enumerate(shape.Faces()):
        try:
            if f.geomType().upper() != "CONE":
                continue
        except Exception:
            continue

        fbb = f.BoundingBox()
        fc = f.Center()

        if (
            f.Area() > 100.0
            and abs(fbb.ymin - cone_tangent_y) < 0.05
            and fbb.ymax > cone_tangent_y + 1.0
            and math.hypot(fc.x, fc.z) < 1.0
        ):
            cone_candidates.append((f.Area(), i, f))

    if not cone_candidates:
        raise RuntimeError("Could not locate parent conical hub/web surface")

    cone_candidates.sort(reverse=True, key=lambda x: x[0])
    _, cone_index, cone_face = cone_candidates[0]
    cone_bb = cone_face.BoundingBox()
    print(
        f"Parent cone OCC face: {cone_index}, area={cone_face.Area():.6f}, "
        f"Y-range=({cone_bb.ymin:.6f},{cone_bb.ymax:.6f})"
    )

    # ------------------------------------------------------------------
    # 4. Determine the cone slope dr/dY from points on the far boundary of
    # the parent cone. The parent cone is interrupted by spokes/windows,
    # so its upper boundary consists of several arc segments rather than
    # one complete circle. Their vertices still lie on the same cone.
    # ------------------------------------------------------------------
    far_y = cone_bb.ymax
    far_radii = []

    for v in cone_face.Vertices():
        p = v.Center()
        if abs(p.y - far_y) < 0.02:
            r = math.hypot(p.x - axis_x, p.z - axis_z)
            if r > r_cone_tangent + 1.0:
                far_radii.append(r)

    if not far_radii:
        # Fallback to edge sample/centroid radii on the far cone boundary.
        for e in cone_face.Edges():
            ec = e.Center()
            if abs(ec.y - far_y) < 0.03:
                r = math.hypot(ec.x - axis_x, ec.z - axis_z)
                if r > r_cone_tangent + 1.0:
                    far_radii.append(r)

    if not far_radii:
        raise RuntimeError("Could not estimate parent cone slope")

    r_far = statistics.median(far_radii)
    slope = (r_far - r_cone_tangent) / (far_y - cone_tangent_y)

    if slope <= 0.1:
        raise RuntimeError(f"Unexpected cone slope {slope}")

    print(f"Cone reference far point: R={r_far:.6f}, Y={far_y:.6f}")
    print(f"Derived cone slope dR/dY={slope:.6f}")

    # Extend the parent cone back to the front planar face. This gives the
    # sharp theoretical corner that existed before the original fillet.
    r_corner = r_cone_tangent + slope * (front_y - cone_tangent_y)
    print(f"Unfilleted sharp parent intersection: R={r_corner:.6f}, Y={front_y:.6f}")

    if not (r_front_tangent - 1.0 < r_corner < r_cone_tangent + 1.0):
        raise RuntimeError(
            "Computed sharp parent intersection is inconsistent with fillet boundaries"
        )

    # ------------------------------------------------------------------
    # 5. REMOVE FILLET by restoring the original sharp parent surfaces.
    #
    # Merely cutting the existing fillet is insufficient: an external
    # rounded fillet already removed material relative to the theoretical
    # sharp plane/cone corner. Therefore first restore that local material
    # using a revolved annular wedge bounded by the front plane and the
    # extrapolated parent cone. The union overlaps the existing body
    # everywhere except the material previously removed by the fillet.
    # ------------------------------------------------------------------
    restore_inner_r = max(0.0, min(r_front_tangent, r_corner) - 0.75)
    restore_outer_r = r_cone_tangent + 0.75

    def cone_y_at_r(r):
        return front_y + (r - r_corner) / slope

    restore_outer_y = cone_y_at_r(restore_outer_r)
    interior_y = max(cone_tangent_y + 0.8, restore_outer_y + 0.5)

    print("Restore-parent profile:")
    print(f" P1 R={restore_inner_r:.6f}, Y={front_y:.6f}")
    print(f" P2 R={r_corner:.6f}, Y={front_y:.6f}")
    print(f" P3 R={restore_outer_r:.6f}, Y={restore_outer_y:.6f}")

    restore_tool = (
        cq.Workplane("XY")
        .moveTo(restore_inner_r, front_y)
        .lineTo(r_corner, front_y)
        .lineTo(restore_outer_r, restore_outer_y)
        .lineTo(restore_outer_r, interior_y)
        .lineTo(restore_inner_r, interior_y)
        .close()
        .revolve(360.0, (0.0, 0.0), (0.0, 1.0))
        .translate((axis_x, 0.0, axis_z))
    )

    restored = cq.Workplane(obj=shape).union(restore_tool)
    restored_shape = restored.val()

    print(f"After parent restoration valid: {restored_shape.isValid()}")
    print(f"After parent restoration volume: {restored_shape.Volume():.6f}")
    print(f"Restored material volume: {restored_shape.Volume() - shape.Volume():.6f}")

    if not restored_shape.isValid():
        raise RuntimeError("Parent-surface restoration produced invalid geometry")

    # ------------------------------------------------------------------
    # 6. ADD REQUESTED 1 mm CHAMFER.
    #
    # Treat the unspecified 1 mm chamfer as an equal-distance chamfer.
    # One endpoint lies 1 mm radially inward along the front planar parent;
    # the other lies 1 mm along the conical parent generatrix.
    # ------------------------------------------------------------------
    chamfer_size = 1.0

    p1_r = r_corner - chamfer_size
    p1_y = front_y

    # Unit direction along cone generatrix in the outward/+Y direction.
    cone_norm = math.sqrt(slope * slope + 1.0)
    p2_r = r_corner + chamfer_size * slope / cone_norm
    p2_y = front_y + chamfer_size / cone_norm

    print("1 mm equal-distance chamfer endpoints:")
    print(f" Plane endpoint: R={p1_r:.6f}, Y={p1_y:.6f}")
    print(f" Cone endpoint: R={p2_r:.6f}, Y={p2_y:.6f}")
    print(
        f" Plane distance={abs(r_corner - p1_r):.6f}, "
        f"cone distance={math.hypot(p2_r - r_corner, p2_y - front_y):.6f}"
    )

    # Remove the triangular corner lying in front of the new straight
    # chamfer line. Extend the cutting profile slightly outside the body on
    # the negative-Y side to ensure a robust Boolean operation.
    cutter_front_y = front_y - 1.5

    chamfer_cutter = (
        cq.Workplane("XY")
        .moveTo(p1_r, cutter_front_y)
        .lineTo(p1_r, p1_y)
        .lineTo(p2_r, p2_y)
        .lineTo(p2_r, cutter_front_y)
        .close()
        .revolve(360.0, (0.0, 0.0), (0.0, 1.0))
        .translate((axis_x, 0.0, axis_z))
    )

    result = restored.cut(chamfer_cutter).clean()
    out = result.val()

    print("=== FINAL EDIT VALIDATION ===")
    print(f"Result valid: {out.isValid()}")
    print(f"Result volume: {out.Volume():.6f}")
    print(f"Net volume change from original: {out.Volume() - shape.Volume():.6f}")
    print(f"Result faces: {len(out.Faces())}")

    if not out.isValid():
        raise RuntimeError("Final chamfered body is invalid")

    # Verify the old large front-center torus is no longer exposed and
    # report replacement conical faces around the edited region.
    remaining_target_tori = []
    replacement_cones = []

    for i, f in enumerate(out.Faces()):
        try:
            gt = f.geomType().upper()
        except Exception:
            continue
        fc = f.Center()
        fbb = f.BoundingBox()

        if (
            gt == "TORUS"
            and f.Area() > 100.0
            and math.hypot(fc.x - axis_x, fc.z - axis_z) < 0.5
            and fc.y < -3.5
        ):
            remaining_target_tori.append((i, f.Area(), fc.y))

        if (
            gt == "CONE"
            and fbb.ymin <= p1_y + 0.05
            and fbb.ymax >= p2_y - 0.05
            and fc.y < -3.5
        ):
            replacement_cones.append((i, f.Area(), fc.y, fbb.ymin, fbb.ymax))

    print(f"Remaining large front-center torus count: {len(remaining_target_tori)}")
    for row in remaining_target_tori:
        print(f" TORUS {row}")

    print(f"Candidate replacement cone count: {len(replacement_cones)}")
    for row in replacement_cones:
        print(f" CONE {row}")

    return result
