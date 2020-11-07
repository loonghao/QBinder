# -*- coding: utf-8 -*-
"""

"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2020-11-03 15:55:15"

import os
import sys

repo = (lambda f: lambda p=__file__: f(f, p))(
    lambda f, p: p
    if [
        d
        for d in os.listdir(p if os.path.isdir(p) else os.path.dirname(p))
        if d == ".git"
    ]
    else None
    if os.path.dirname(p) == p
    else f(f, os.path.dirname(p))
)()
sys.path.insert(0, repo) if repo not in sys.path else None

from QBinder import Binder, GBinder
from Qt import QtGui, QtWidgets, QtCore

state = GBinder()
state.msg = "msg"
state.num = 1
# state.text = 'text'


class ButtonTest(QtWidgets.QWidget):
    count = 1
    def __init__(self):
        super(ButtonTest, self).__init__()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        button = QtWidgets.QPushButton("click me")
        layout.addWidget(button)
        label = QtWidgets.QLabel()
        layout.addWidget(label)
        label.setText(lambda: state.num)

        button.clicked.connect(self.callback)

    @state("fn_bind", "click_event")
    def callback(self):
        self.count += self.count
        state.num += self.count
        print("[%s] click me" % self.__class__.__name__)


class ButtonTest2(QtWidgets.QWidget):
    def __init__(self):
        super(ButtonTest2, self).__init__()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        button = QtWidgets.QPushButton("click me ButtonTest2")
        layout.addWidget(button)
        print(state.click_event)
        button.clicked.connect(state.click_event[state.input_ui])


if __name__ == "__main__":

    app = QtWidgets.QApplication(sys.argv)
    state.input_ui = ButtonTest()
    state.input_ui.show()

    widget = ButtonTest2()
    widget.show()
    sys.exit(app.exec_())