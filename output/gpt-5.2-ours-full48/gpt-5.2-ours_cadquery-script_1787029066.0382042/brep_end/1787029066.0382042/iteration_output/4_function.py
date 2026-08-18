def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    shape = cq.importers.importStep(input_file).val()

    print("=== Loaded model ===")
    try:
        print("Valid:", shape.isValid())
    except Exception:
        pass

    solids = list(shape.Solids())
    print("Solids:", len(solids))
    bb = shape.BoundingBox()
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    midY = bb.center.y
    midZ = bb.center.z
    yr = max(1e-6, bb.ymax - bb.ymin)
    zr = max(1e-6, bb.zmax - bb.zmin)
    xr = max(1e-6, bb.xmax - bb.xmin)

    # Heuristic: find existing small "port" solids near TOP-LEFT and BOTTOM-RIGHT,
    # then mirror across plane y=midY to create TOP-RIGHT and BOTTOM-LEFT.
    # If no suitable source solid is found, create simple hollow tube ports at targets.

    def sbox(s):
        return s.BoundingBox()

    def dims(sb):
        return (sb.xmax - sb.xmin, sb.ymax - sb.ymin, sb.zmax - sb.zmin)

    def is_small_portish(sb):
        dx, dy, dz = dims(sb)
        # reject very large parts
        if dx > 120 or dy > 120 or dz > 140:
            return False
        # reject tiny fillet solids
        if max(dx, dy, dz) < 8:
            return False
        # port-like: one dimension somewhat larger than the other two
        d = sorted([dx, dy, dz])
        if d[2] < 12:
            return False
        if d[2] / max(1e-6, d[1]) < 1.25:
            return False
        return True

    def vol(s):
        try:
            return float(s.Volume())
        except Exception:
            return 0.0

    # Candidate selection windows (in YZ corners of the 'right' view):
    # top-left  => y < midY, z > midZ and near zmax
    # bottom-right => y > midY, z < midZ and near zmin
    z_top_band = bb.zmax - 0.08 * zr  # top 8%
    z_bot_band = bb.zmin + 0.08 * zr  # bottom 8%

    y_left_band = bb.ymin + 0.25 * yr
    y_right_band = bb.ymax - 0.25 * yr

    src_top_left = None
    src_top_left_i = None
    best_score = -1e9
    for i, s in enumerate(solids):
        sb = sbox(s)
        if not is_small_portish(sb):
            continue
        cy = 0.5 * (sb.ymin + sb.ymax)
        cz = 0.5 * (sb.zmin + sb.zmax)
        # near top and on left side
        if sb.zmax < z_top_band:
            continue
        if cy >= midY:
            continue
        if sb.ymax > y_left_band:
            # still allow, but prefer closer to ymin side
            pass
        # prefer very top and further left
        score = (sb.zmax - bb.zmin) / zr + (midY - cy) / yr + 0.002 * vol(s)
        if score > best_score:
            best_score = score
            src_top_left = s
            src_top_left_i = i

    src_bot_right = None
    src_bot_right_i = None
    best_score = -1e9
    for i, s in enumerate(solids):
        sb = sbox(s)
        if not is_small_portish(sb):
            continue
        cy = 0.5 * (sb.ymin + sb.ymax)
        cz = 0.5 * (sb.zmin + sb.zmax)
        # near bottom and on right side
        if sb.zmin > z_bot_band:
            continue
        if cy <= midY:
            continue
        score = (bb.zmax - sb.zmin) / zr + (cy - midY) / yr + 0.002 * vol(s)
        if score > best_score:
            best_score = score
            src_bot_right = s
            src_bot_right_i = i

    print("=== Source detection ===")
    if src_top_left is not None:
        sb = sbox(src_top_left)
        dx, dy, dz = dims(sb)
        print(f"Top-left source solid idx={src_top_left_i} dims=({dx:.2f},{dy:.2f},{dz:.2f}) y=({sb.ymin:.2f},{sb.ymax:.2f}) z=({sb.zmin:.2f},{sb.zmax:.2f})")
    else:
        print("Top-left source solid: NOT FOUND")

    if src_bot_right is not None:
        sb = sbox(src_bot_right)
        dx, dy, dz = dims(sb)
        print(f"Bottom-right source solid idx={src_bot_right_i} dims=({dx:.2f},{dy:.2f},{dz:.2f}) y=({sb.ymin:.2f},{sb.ymax:.2f}) z=({sb.zmin:.2f},{sb.zmax:.2f})")
    else:
        print("Bottom-right source solid: NOT FOUND")

    # Robust mirror across plane y=midY (plane normal +Y)
    def mirror_solid_about_midY(solid):
        from OCP.gp import gp_Pln, gp_Pnt, gp_Dir, gp_Trsf
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        pln = gp_Pln(gp_Pnt(0.0, float(midY), 0.0), gp_Dir(0.0, 1.0, 0.0))
        tr = gp_Trsf()
        tr.SetMirror(pln)
        moved = BRepBuilderAPI_Transform(solid.wrapped, tr, True).Shape()
        return cq.Solid.cast(moved)

    # Fallback: create a simple hollow tube (hose nipple) pointing out of top/bottom.
    def make_hollow_tube(center_xyz, axis_dir, outer_d=16.0, inner_d=10.0, length=35.0, lip=3.0):
        # center_xyz is the center of the tube along its axis
        cx, cy, cz = center_xyz
        ax = cq.Vector(*axis_dir)
        L = math.sqrt(ax.x*ax.x + ax.y*ax.y + ax.z*ax.z)
        if L < 1e-9:
            ax = cq.Vector(0, 0, 1)
        else:
            ax = cq.Vector(ax.x/L, ax.y/L, ax.z/L)

        outer_r = outer_d / 2.0
        inner_r = inner_d / 2.0

        base = cq.Vector(cx, cy, cz) - ax * (length / 2.0)
        outer = cq.Solid.makeCylinder(outer_r, length, base, ax)
        # make the bore slightly longer to guarantee through-cut
        inner_base = base - ax * 1.0
        inner = cq.Solid.makeCylinder(inner_r, length + 2.0, inner_base, ax)
        tube = outer.cut(inner)

        # add a small lip/bead near the tip for a hose clamp look
        bead_r = outer_r * 1.12
        bead_len = max(1.5, min(5.0, lip))
        bead_base = cq.Vector(cx, cy, cz) + ax * (length / 2.0 - bead_len)
        bead = cq.Solid.makeCylinder(bead_r, bead_len, bead_base, ax)
        bead = bead.cut(cq.Solid.makeCylinder(inner_r, bead_len + 0.5, bead_base - ax * 0.25, ax))

        return tube.union(bead)

    added = []
    ok_out = False
    ok_in = False

    # 1) Outlet port: TOP-RIGHT. Prefer mirroring a TOP-LEFT existing port solid.
    if src_top_left is not None:
        try:
            out_port = mirror_solid_about_midY(src_top_left)
            added.append(out_port)
            ok_out = True
            sb = sbox(out_port)
            print(f"Outlet (top-right): mirrored from top-left. New y=({sb.ymin:.2f},{sb.ymax:.2f}) z=({sb.zmin:.2f},{sb.zmax:.2f})")
        except Exception as e:
            print("Outlet mirror failed, will fallback to synthetic tube:", e)

    if not ok_out:
        # synthetic: place near the top-right corner, extruding +Z
        x_place = bb.xmin + 0.15 * xr  # keep away from fan side features
        y_place = bb.ymax - 0.08 * yr
        z_place = bb.zmax - 0.01 * zr
        out_port = make_hollow_tube((x_place, y_place, z_place + 18.0), (0, 0, 1), outer_d=16.0, inner_d=10.0, length=36.0)
        added.append(out_port)
        ok_out = True
        print("Outlet (top-right): created synthetic vertical tube at approx top-right.")

    # 2) Inlet port: BOTTOM-LEFT. Prefer mirroring a BOTTOM-RIGHT existing port solid.
    if src_bot_right is not None:
        try:
            in_port = mirror_solid_about_midY(src_bot_right)
            added.append(in_port)
            ok_in = True
            sb = sbox(in_port)
            print(f"Inlet (bottom-left): mirrored from bottom-right. New y=({sb.ymin:.2f},{sb.ymax:.2f}) z=({sb.zmin:.2f},{sb.zmax:.2f})")
        except Exception as e:
            print("Inlet mirror failed, will fallback to synthetic tube:", e)

    if not ok_in:
        # synthetic: place near the bottom-left corner, extruding -Z
        x_place = bb.xmin + 0.15 * xr
        y_place = bb.ymin + 0.08 * yr
        z_place = bb.zmin + 0.01 * zr
        in_port = make_hollow_tube((x_place, y_place, z_place - 18.0), (0, 0, -1), outer_d=16.0, inner_d=10.0, length=36.0)
        added.append(in_port)
        ok_in = True
        print("Inlet (bottom-left): created synthetic vertical tube at approx bottom-left.")

    # Return as compound (keep original solids; add new solids as separate bodies)
    out_solids = solids + added
    result = cq.Compound.makeCompound(out_solids)

    print("=== Done ===")
    try:
        print("Result valid:", result.isValid())
    except Exception:
        pass
    print("Result solids:", len(list(result.Solids())))
    print(f"Ports added: outlet={ok_out} inlet={ok_in} (added solids={len(added)})")

    return cq.Workplane().add(result)
