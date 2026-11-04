"""Scrollable pick-from-a-list dialog for Stan's Tools operators.

Blender's `invoke_search_popup` has no scrollbar, and its recent-searches sorting is one global preference, so a menu
cannot opt out of it. This dialog is a `UIList`: mouse wheel, scrollbar and a filter box. Operators opt in to their own
recent picks with `picker_recent_key`.
"""
from __future__ import annotations

__all__ = [
    "ListPickerMixin",
    "StanListPickerItem",
    "StanListPickerList",
    "StanListPickerState",
]

import bpy

from ..base.register import (
    io_soulstruct_class,
    io_soulstruct_pointer_property,
    io_soulstruct_properties,
)
from .remembered_folders import add_recent_pick, get_recent_picks


@io_soulstruct_properties
class StanListPickerItem(bpy.types.PropertyGroup):
    value: bpy.props.StringProperty()
    recent: bpy.props.BoolProperty()


@io_soulstruct_properties
@io_soulstruct_pointer_property(bpy.types.WindowManager, "stan_list_picker")
class StanListPickerState(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=StanListPickerItem)
    index: bpy.props.IntProperty()
    pending: bpy.props.BoolProperty()  # False after a pick, so 'Adjust Last Operation' and direct calls skip the list


@io_soulstruct_class
class StanListPickerList(bpy.types.UIList):
    bl_idname = "STAN_UL_list_picker"

    def __init__(self, *args):
        super().__init__(*args)
        self.use_filter_show = True  # filter box open by default

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index=0, _flt_flag=0):
        layout.label(text=item.name, icon="TIME" if item.recent else "NONE", translate=False)


class ListPickerMixin:
    """Put first in an operator's bases. `invoke` returns `open_picker(...)`; `execute` starts with `picked(...)`."""

    picker_recent_key = ""  # non-empty: remember picks under this key and list them first
    picker_confirm_text = "Load"

    def open_picker(self, context, items: list[tuple]) -> set[str]:
        """Show (identifier, label, ...) `items` in the dialog."""
        picker = context.window_manager.stan_list_picker
        recent = get_recent_picks(self.picker_recent_key) if self.picker_recent_key else []
        items_by_value = {item[0]: item for item in items}
        recent = [value for value in recent if value in items_by_value]
        picker.items.clear()
        for value in recent:
            entry = picker.items.add()
            entry.name, entry.value, entry.recent = items_by_value[value][1], value, True
        for item in items:
            if item[0] not in recent:
                entry = picker.items.add()
                entry.name, entry.value = item[1], item[0]
        picker.index = 0
        picker.pending = True
        return context.window_manager.invoke_props_dialog(self, width=480, confirm_text=self.picker_confirm_text)

    def draw(self, context):
        picker = context.window_manager.stan_list_picker
        if not picker.pending:
            return
        layout = self.layout
        layout.template_list(
            StanListPickerList.bl_idname, "", picker, "items", picker, "index", rows=16, maxrows=16
        )
        if 0 <= picker.index < len(picker.items):
            layout.label(text=picker.items[picker.index].name, icon="RIGHTARROW", translate=False)

    def cancel(self, context):
        context.window_manager.stan_list_picker.pending = False

    def picked(self, context, current: str) -> str:
        """The dialog's pick, or `current` when the operator ran without the dialog."""
        picker = context.window_manager.stan_list_picker
        if not picker.pending:
            return current
        picker.pending = False
        if not 0 <= picker.index < len(picker.items):
            return current
        value = picker.items[picker.index].value
        if self.picker_recent_key:
            add_recent_pick(self.picker_recent_key, value)
        return value
