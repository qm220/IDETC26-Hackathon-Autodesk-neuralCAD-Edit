"""Example CadQuery edit for experiment/run_cadquery.py.

Replace the body of my_cad_function with your own edit.
args["input_file"] is the STEP path passed on the command line.
"""

import os

import cadquery as cq


def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Loaded {input_file}")
    print(f"Faces={len(shape.Faces())} Edges={len(shape.Edges())}")

    # Example: return the loaded solid unchanged.
    # To chamfer all full circular edges by 0.2 mm, you could do:
    #   return cq.Workplane(obj=shape).edges("%CIRCLE").chamfer(0.2)
    return cq.Workplane(obj=shape)
