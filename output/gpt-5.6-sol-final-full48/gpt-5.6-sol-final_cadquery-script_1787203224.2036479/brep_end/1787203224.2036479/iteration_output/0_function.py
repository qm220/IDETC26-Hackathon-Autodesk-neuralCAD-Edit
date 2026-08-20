def my_cad_function(args):
    import os
    import math

    if "input_file" not in args:
        raise ValueError("An input STEP file is required")

    imported = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    source_shape = imported.val() if hasattr(imported, "val") else imported
    source_solids = list(source_shape.Solids())
    if not source_solids:
        raise ValueError("The input STEP file contains no solids")

    # Separate the compact central hub from the two long original blades.
    long_solids = []
    hub_solids = []
    for solid in source_solids:
        bb = solid.BoundingBox()
        planar_span = math.hypot(bb.xlen, bb.ylen)
        if planar_span > 70.0:
            long_solids.append(solid)
        else:
            hub_solids.append(solid)

    if not hub_solids:
        # Fallback: the solid with the smallest XY diagonal is the hub.
        ordered = sorted(
            source_solids,
            key=lambda s: math.hypot(s.BoundingBox().xlen, s.BoundingBox().ylen),
        )
        hub_solids = [ordered[0]]
        long_solids = ordered[1:]

    hub_compound = cq.Compound.makeCompound(hub_solids)
    hub_bb = hub_compound.BoundingBox()
    rotor_center = cq.Vector(
        (hub_bb.xmin + hub_bb.xmax) * 0.5,
        (hub_bb.ymin + hub_bb.ymax) * 0.5,
        (hub_bb.zmin + hub_bb.zmax) * 0.5,
    )

    def principal_angle_and_length(solid):
        vertices = solid.Vertices()
        pts = [(v.X, v.Y) for v in vertices]
        if len(pts) < 2:
            bb = solid.BoundingBox()
            angle = 0.0 if bb.xlen >= bb.ylen else math.pi * 0.5
        else:
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            cxx = sum((p[0] - mx) ** 2 for p in pts)
            cyy = sum((p[1] - my) ** 2 for p in pts)
            cxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
            angle = 0.5 * math.atan2(2.0 * cxy, cxx - cyy)

        ux, uy = math.cos(angle), math.sin(angle)
        projections = [
            (v.X - rotor_center.x) * ux + (v.Y - rotor_center.y) * uy
            for v in solid.Vertices()
        ]
        length = max(projections) - min(projections) if projections else 203.2
        return angle % math.pi, length

    measured = [principal_angle_and_length(s) for s in long_solids[:2]]
    if len(measured) >= 2:
        blade_angles = [measured[0][0], measured[1][0]]
        blade_length = sum(item[1] for item in measured) / len(measured)
    else:
        blade_angles = [math.radians(30.0), math.radians(90.0)]
        blade_length = 203.2

    # Avoid unreasonable dimensions if tessellation/topology gives an outlier.
    if not (150.0 <= blade_length <= 260.0):
        blade_length = 203.2

    def axial_angle_distance(a, b):
        d = abs((a - b) % math.pi)
        return min(d, math.pi - d)

    # Choose the unused axis that maximizes separation from both existing axes.
    best_angle = 0.0
    best_score = -1.0
    for i in range(720):
        candidate = math.pi * i / 720.0
        score = min(axial_angle_distance(candidate, a) for a in blade_angles)
        if score > best_score:
            best_score = score
            best_angle = candidate
    blade_angles.append(best_angle)

    blade_width = 12.70
    full_thickness = 3.175
    web_thickness = 0.42
    layer_gap = 0.08
    layer_pitch = web_thickness + layer_gap
    edge_radius = 0.20
    central_boss_radius = 9.525
    pivot_radius = 6.477
    end_bore_radius = 3.175
    end_bore_depth = 19.0
    web_half_length = 15.5
    ramp_outer = 23.0

    def make_ramp(x0, x1, z_inner, right_side=True):
        zi0 = z_inner - web_thickness * 0.5
        zi1 = z_inner + web_thickness * 0.5
        zo0 = -full_thickness * 0.5
        zo1 = full_thickness * 0.5
        if right_side:
            points = [(x0, zi0), (x1, zo0), (x1, zo1), (x0, zi1)]
        else:
            points = [(-x1, zo0), (-x0, zi0), (-x0, zi1), (-x1, zo1)]
        return (
            cq.Workplane("XZ")
            .polyline(points)
            .close()
            .extrude(blade_width * 0.5, both=True)
        )

    def make_blade(angle_radians, central_z):
        half_length = blade_length * 0.5
        outer_start = ramp_outer - 0.10
        arm_length = half_length - outer_start
        if arm_length <= 20.0:
            raise ValueError("Measured blade length is too short")

        right_arm = (
            cq.Workplane("XY")
            .box(arm_length, blade_width, full_thickness)
            .translate(((outer_start + half_length) * 0.5, 0, 0))
            .edges("|X")
            .fillet(edge_radius)
        )
        left_arm = (
            cq.Workplane("XY")
            .box(arm_length, blade_width, full_thickness)
            .translate((-(outer_start + half_length) * 0.5, 0, 0))
            .edges("|X")
            .fillet(edge_radius)
        )

        # The center web is only 0.42 mm thick and is independently positioned
        # within the three-layer stack. Its four long edges receive R0.20.
        center_web = (
            cq.Workplane("XY")
            .box(2.0 * (web_half_length + 0.10), blade_width, web_thickness)
            .translate((0, 0, central_z))
            .edges("|X")
            .fillet(edge_radius)
        )
        center_boss = (
            cq.Workplane("XY")
            .workplane(offset=central_z)
            .circle(central_boss_radius)
            .extrude(web_thickness * 0.5, both=True)
        )

        right_ramp = make_ramp(web_half_length, ramp_outer, central_z, True)
        left_ramp = make_ramp(web_half_length, ramp_outer, central_z, False)

        blade = right_arm.union(left_arm)
        blade = blade.union(right_ramp).union(left_ramp)
        blade = blade.union(center_web).union(center_boss)

        # Preserve the common central axle interface.
        pivot_hole = cq.Solid.makeCylinder(
            pivot_radius,
            full_thickness + abs(central_z) * 2.0 + 4.0,
            cq.Vector(0, 0, -full_thickness * 0.5 - abs(central_z) - 2.0),
            cq.Vector(0, 0, 1),
        )
        blade = blade.cut(pivot_hole)

        # Matching axial attachment bores at both remote ends.
        left_bore = cq.Solid.makeCylinder(
            end_bore_radius,
            end_bore_depth,
            cq.Vector(-half_length - 0.01, 0, 0),
            cq.Vector(1, 0, 0),
        )
        right_bore = cq.Solid.makeCylinder(
            end_bore_radius,
            end_bore_depth,
            cq.Vector(half_length + 0.01, 0, 0),
            cq.Vector(-1, 0, 0),
        )
        blade = blade.cut(left_bore).cut(right_bore)

        blade = blade.rotate((0, 0, 0), (0, 0, 1), math.degrees(angle_radians))
        blade = blade.translate((rotor_center.x, rotor_center.y, rotor_center.z))
        return blade.val()

    # Existing members occupy the two outer layers; the new third blade passes
    # through the exact center of the stack.
    layer_offsets = [-layer_pitch, layer_pitch, 0.0]
    blades = [
        make_blade(blade_angles[i], layer_offsets[i])
        for i in range(3)
    ]

    result_solids = list(hub_solids) + blades
    result = cq.Compound.makeCompound(result_solids)

    print("Preserved hub solids:", len(hub_solids))
    print("Rebuilt matching blades: 3")
    print("Blade angles (deg):", [round(math.degrees(a), 3) for a in blade_angles])
    print("Nominal central web thickness: 0.42 mm")
    print("New blade layer offset: 0.0 mm (center of stack)")
    print("Longitudinal edge radius: 0.20 mm")
    print("Result valid:", result.isValid())
    return cq.Workplane(obj=result)
