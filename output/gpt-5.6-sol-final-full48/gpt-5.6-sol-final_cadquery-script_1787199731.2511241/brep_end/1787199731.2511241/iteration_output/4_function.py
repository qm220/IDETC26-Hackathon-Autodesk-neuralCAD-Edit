def my_cad_function(args):
    import cadquery as cq
    import os
    return cq.importers.importStep(os.path.expanduser(args["input_file"]))