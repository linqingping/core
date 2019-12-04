"""
class for shapes
"""
import logging

from coretk.dialogs.shapemod import ShapeDialog
from coretk.images import ImageEnum

ABOVE_COMPONENT = ["gridline", "edge", "linkinfo", "antenna", "node", "nodename"]


class ShapeData:
    def __init__(self):
        self.text = ""
        self.font = "Arial"
        self.font_size = 12
        self.text_color = "#000000"
        self.fill_color = "#CFCFFF"
        self.border_color = "#000000"
        self.border_width = 0
        self.bold = 0
        self.italic = 0
        self.underline = 0


class Shape:
    def __init__(self, app, canvas, top_x, top_y):
        self.app = app
        self.canvas = canvas
        self.x0 = top_x
        self.y0 = top_y
        self.cursor_x = None
        self.cursor_y = None
        self.created = False
        self.text_id = None

        self.shape_data = ShapeData()
        canvas.delete(canvas.find_withtag("selectednodes"))
        annotation_type = self.canvas.annotation_type
        if annotation_type == ImageEnum.OVAL:
            self.id = canvas.create_oval(
                top_x, top_y, top_x, top_y, tags="shape", dash="-"
            )
        elif annotation_type == ImageEnum.RECTANGLE:
            self.id = canvas.create_rectangle(
                top_x, top_y, top_x, top_y, tags="shape", dash="-"
            )
        self.canvas.tag_bind(self.id, "<ButtonRelease-1>", self.click_release)
        # self.canvas.tag_bind(self.id, "<B1-Motion>", self.motion)

    def shape_motion(self, x1, y1):
        self.canvas.coords(self.id, self.x0, self.y0, x1, y1)

    def shape_complete(self, x, y):
        for component in ABOVE_COMPONENT:
            self.canvas.tag_raise(component)
        s = ShapeDialog(self.app, self.app, self)
        s.show()

    def click_release(self, event):
        logging.debug("Click release on shape %s", self.id)

    def motion(self, event):
        logging.debug("motion on shape %s", self.id)
        delta_x = event.x - self.cursor_x
        delta_y = event.y - self.cursor_y
        x0, y0, x1, y1 = self.canvas.bbox(self.id)
        self.canvas.coords(
            self.id, x0 + delta_x, y0 + delta_y, x1 + delta_x, y1 + delta_y
        )
        self.canvas.canvas_management.node_drag(self, delta_x, delta_y)
        self.cursor_x = event.x
        self.cursor_y = event.y
