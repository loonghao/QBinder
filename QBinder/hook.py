# -*- coding: utf-8 -*-
"""

"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from __future__ import unicode_literals

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2020-11-02 23:47:53"

import re
import sys
import six
import types
import inspect
from functools import partial

import Qt
from Qt import QtCore
from Qt import QtWidgets
from Qt import QtGui
from Qt.QtCompat import isValid

from .util import nestdict
from .hookconfig import CONFIG

HOOKS = nestdict()
_HOOKS_REL = nestdict()
qt_dict = {"QtWidgets.%s" % n: m for n, m in inspect.getmembers(QtWidgets)}
qt_dict.update({"QtCore.%s" % n: m for n, m in inspect.getmembers(QtCore)})
qt_dict.update({"QtGui.%s" % n: m for n, m in inspect.getmembers(QtGui)})

def _cell_factory():
    a = 1
    f = lambda: a + 1
    return f.__closure__[0]

CellType = type(_cell_factory())

def byte2str(text):
    """Convert bytes to str in both Python 2 and 3.
    
    Args:
        text: The text to convert
        
    Returns:
        str: The converted string
    """
    if isinstance(text, six.binary_type):
        return text.decode('utf-8')
    return six.text_type(text)

def get_method_name(method):
    # NOTE compat Qt 4 and 5
    version = QtCore.qVersion()
    name = ""
    count = False
    if version.startswith("5"):
        name = method.name()
        count = method.parameterCount()
    elif version.startswith("4"):
        name = method.signature()
        name = name.split("(")[0]
        count = method.parameterNames()
    return byte2str(name), count

def get_property_count(meta_obj):
    if not isinstance(meta_obj, QtCore.QMetaObject):
        return
    try:
        # Check if the object is still valid before accessing
        if hasattr(meta_obj, 'propertyCount') and isValid(meta_obj):
            count = meta_obj.propertyCount()
            return count
    except RuntimeError:
        pass
    return None

def safe_property_access(obj, property_name, default=None):
    """Safely access a Qt object's property.
    
    Args:
        obj: The Qt object to access
        property_name: Name of the property to access
        default: Default value if property cannot be accessed
        
    Returns:
        The property value or default if access fails
    """
    try:
        if obj and isinstance(obj, QtCore.QObject) and isValid(obj):
            return obj.property(property_name)
        return default
    except Exception:
        return default

def safe_widget_call(func):
    """Decorator to safely call Qt widget methods.
    
    Args:
        func: The function to wrap
        
    Returns:
        wrapper: The wrapped function
    """
    @six.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            if not self or not isinstance(self, QtCore.QObject) or not isValid(self):
                return None
            return func(self, *args, **kwargs)
        except Exception as e:
            error_msg = six.text_type(e)
            if "already deleted" in error_msg or "wrapped C/C++ object" in error_msg:
                return None
            raise
    return wrapper


def _initialize():
    """Initialize the HOOKS dictionary with Qt widget information.
    
    This function scans Qt widgets and their properties to populate the HOOKS
    dictionary, but does not perform the actual hook initialization.
    """
    for name, member in qt_dict.items():
        # NOTE filter qt related func
        if name == "QtGui.QMatrix" or not hasattr(member, "staticMetaObject"):
            continue
        data = CONFIG.get(name, {})
        for method_name, _ in inspect.getmembers(member, inspect.isroutine):
            if data.get(method_name):
                HOOKS[name][method_name] = {}
                if method_name.startswith("set"):
                    _HOOKS_REL[method_name.lower()] = method_name

        # NOTE auto bind updater
        meta_obj = getattr(member, "staticMetaObject", None)
        count = get_property_count(meta_obj)
        if count is None and issubclass(member, QtCore.QObject):
            meta_obj = member().metaObject()

        if count:
            for i in range(count):
                property = meta_obj.property(i)
                property_name = byte2str(property.name())
                updater = "set%s%s" % (
                    property_name[0].upper(),
                    property_name[1:],
                )
                if updater:
                    data.update({"updater": updater, "property": property_name})

class HookMeta(type):
    def __call__(self, func=None):
        if callable(func):
            return self()(func)
        else:
            return super(HookMeta, self).__call__(func)

class HookBase(six.with_metaclass(HookMeta, object)):
    def __init__(self, options=None):
        self.options = options if options else {}

    @classmethod
    def combine_args(cls, val, args):
        if isinstance(val, tuple):
            return val + args[1:]
        else:
            return (val,) + args[1:]

    @classmethod
    def trace_callback(cls, callback, self=None):
        """trigger all possible binder binding __get__ call"""
        pattern = "QBinder.binder.*BinderInstance"
        closure = getattr(callback, "__closure__", None)
        closure = closure if closure else [self] if self else []
        code = callback.__code__
        names = code.co_names

        for cell in closure:
            self = cell.cell_contents if isinstance(cell, CellType) else cell
            for name in names:
                binder = getattr(self, name, None)
                if not binder:
                    continue
                if re.search(pattern, str(binder.__class__)):
                    for _name in names:
                        getattr(binder, _name, None)
                # NOTE `lambda: self.callback()` hook class callback
                elif callable(binder):
                    cls.trace_callback(binder, self)

def check_qt_objects(func):
    """A decorator to check Qt object validity and handle deletion.
    
    Args:
        func: The function to be wrapped
        
    Returns:
        wrapper: The wrapped function that handles Qt object validity
    """
    @six.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Check if any Qt objects are still valid
            qt_objects_valid = True
            for arg in args:
                if isinstance(arg, QtCore.QObject):
                    # Check both object validity and parent widget validity
                    if not isValid(arg) or (hasattr(arg, 'parent') and arg.parent() is None):
                        qt_objects_valid = False
                        break
            if not qt_objects_valid:
                return None
            return func(*args, **kwargs)
        except (RuntimeError, AttributeError) as e:
            error_msg = six.text_type(e)
            if "already deleted" in error_msg or "wrapped C/C++ object" in error_msg:
                return None
            raise
    return wrapper

class MethodHook(HookBase):
    @staticmethod
    def auto_dump(binding):
        """Auto dump for two way binding.
        
        This method handles the automatic dumping of bindings based on the AUTO_DUMP
        configuration. It also sets up the dumper filters for the binding.
        
        Args:
            binding: The binding object to handle
            
        Returns:
            The result of binding.dump() if AUTO_DUMP is enabled and binding exists
        """
        from .constant import AUTO_DUMP

        if not binding:
            return None
            
        try:
            binder = getattr(binding, '__binder__', None)
            if not AUTO_DUMP or not binder:
                return None
                
            # Get the dumper and set up filters
            dumper = binder("dumper")
            if dumper and hasattr(binder, '_var_dict_'):
                for key, value in binder._var_dict_.items():
                    if value is binding:
                        dumper._filters_.add(key)
                        break
                        
            return binding.dump()
            
        except Exception as e:
            error_msg = six.text_type(e)
            print("Error in auto_dump: {}".format(error_msg))
            return None

    @staticmethod
    def remember_cursor_position(callback):
        """maintain the Qt edit cusorPosition after setting a new value"""

        @safe_widget_call
        def wrapper(self, *args, **kwargs):
            setter = None
            cursor_pos = 0
            
            # Use safe property access
            pos = safe_property_access(self, "cursorPosition")
            
            # NOTE for editable combobox
            if pos and isinstance(self, QtWidgets.QComboBox):
                edit = self.lineEdit()
                pos = safe_property_access(edit, "cursorPosition")
            elif isinstance(self, QtWidgets.QTextEdit):
                cursor = self.textCursor()
                cursor_pos = cursor.position() if cursor else 0

            result = callback(self, *args, **kwargs)

            # Only set properties if object is still valid
            if isValid(self):
                if cursor_pos and isinstance(self, QtWidgets.QTextEdit):
                    total = len(self.toPlainText())
                    cursor = self.textCursor()
                    if cursor:
                        cursor.setPosition(total if cursor_pos > total else cursor_pos)
                        setter = partial(self.setTextCursor, cursor)
                elif pos is not None:
                    setter = partial(self.setProperty, "cursorPosition", pos)

                if callable(setter):
                    QtCore.QTimer.singleShot(0, setter)

            return result

        return wrapper

    def __call__(self, func):
        from .binding import Binding

        @six.wraps(func)
        def wrapper(_self, *args, **kwargs):
            callback = args[0] if args else None
            if isinstance(callback, types.LambdaType):

                # NOTE get the running bindings (with __get__ method) add to Binding._trace_dict_
                with Binding.set_trace():
                    val = callback()
                    self.trace_callback(callback)

                # NOTE *_args, **_kwargs for custom argument
                def connect_callback(callback, args, *_args, **_kwargs):
                    args = self.combine_args(callback(), args)
                    self.remember_cursor_position(func)(_self, *args, **kwargs)
                    # TODO some case need to delay for cursor position but it would broke the slider sync effect
                    # QtCore.QTimer.singleShot(
                    #     0,
                    #     lambda: cls.remember_cursor_position(func)(self, *args, **kwargs),
                    # )

                # NOTE register auto update
                _callback_ = partial(connect_callback, callback, args)
                for binding in Binding._trace_dict_.values():
                    binding.connect(_callback_)
                args = self.combine_args(val, args)

                # NOTE Single binding connect to the updater
                updater = self.options.get("updater")
                prop = self.options.get("property")
                getter = self.options.get("getter")
                _getter_1 = getattr(_self, getter) if getter else None
                _getter_2 = lambda: _self.property(prop) if prop else None
                getter = _getter_1 if _getter_1 else _getter_2
                code = callback.__code__

                if (
                    updater
                    and getter
                    # NOTE only bind one response variable
                    and len(Binding._trace_dict_) == 1
                    and len(code.co_consts) == 1  # NOTE only bind directly variable
                ):
                    updater = getattr(_self, updater)
                    updater.connect(lambda *args: binding.set(getter()))
                    binding = list(Binding._trace_dict_.values())[0]
                    QtCore.QTimer.singleShot(0, partial(self.auto_dump, binding))

            return func(_self, *args, **kwargs)

        return wrapper

class FuncHook(HookBase):
    def __call__(self, func):
        from .binding import Binding

        @six.wraps(func)
        @check_qt_objects
        def wrapper(*args, **kwargs):
            if len(args) != 1:
                return func(*args, **kwargs)

            callback = args[0]
            if not callback:
                return None

            try:
                if isinstance(callback, types.LambdaType):
                    # NOTE get the running bindings (with __get__ method) add to Binding._trace_dict_
                    with Binding.set_trace():
                        val = callback()
                        if val is None:  # Early return if callback returns None
                            return None
                        self.trace_callback(callback)

                    def connect_callback(callback, args):
                        try:
                            val = callback()
                            if val is not None:  # Only proceed if we get a valid value
                                args = self.combine_args(val, args)
                                func(*args, **kwargs)
                        except Exception as e:
                            if "already deleted" not in six.text_type(e):
                                raise

                    # NOTE register auto update
                    _callback_ = partial(connect_callback, callback, args[1:])
                    for binding in Binding._trace_dict_.values():
                        if binding is not None:  # Check if binding is still valid
                            binding.connect(_callback_)

                    args = self.combine_args(val, args[1:])
                return func(*args, **kwargs)
                
            except Exception as e:
                if "already deleted" in six.text_type(e):
                    return None
                raise

        return wrapper

def hook_initialize(hooks):
    """Dynamic wrap the Qt Widget setter based on the HOOKS Definition.
    
    This function wraps Qt Widget setters with MethodHook to enable property binding
    and event handling. It safely handles cases where widgets or methods might not exist.
    
    Args:
        hooks (dict): Dictionary containing widget and setter mappings
            Format: {"QtWidgets.WidgetName": {"setterName": options}}
    """
    for widget_path, setters in hooks.items():
        try:
            # Split module and widget name
            lib, widget_name = widget_path.split(".")
            # Get the Qt module (QtWidgets, QtCore, etc)
            qt_module = getattr(Qt, lib, None)
            if qt_module is None:
                continue
                
            # Get the widget class
            widget_class = getattr(qt_module, widget_name, None)
            if widget_class is None:
                continue
                
            # Wrap each setter method
            for setter, options in setters.items():
                try:
                    # Get the original setter method
                    original_func = getattr(widget_class, setter, None)
                    if original_func is not None:
                        # First wrap with safe_widget_call, then with MethodHook
                        safe_func = safe_widget_call(original_func)
                        wrapped = MethodHook(options)(safe_func)
                        setattr(widget_class, setter, wrapped)
                except (AttributeError, TypeError) as e:
                    error_msg = six.text_type(e)
                    print("Error wrapping setter {}.{}: {}".format(
                        widget_path, setter, error_msg))
                    continue
        except Exception as e:
            error_msg = six.text_type(e)
            print("Error processing widget {}: {}".format(
                widget_path, error_msg))
            continue

_initialize()
