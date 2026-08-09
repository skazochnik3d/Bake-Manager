import json
import os
import sys
import traceback
import ctypes
import glob
import re
import time
import math
import shutil
import subprocess
import tempfile
import zipfile
import urllib.error
import urllib.request
from pathlib import Path
from ctypes import wintypes
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

import substance_painter.baking
import substance_painter.event
import substance_painter.export
import substance_painter.project
import substance_painter.layerstack as layerstack
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset
import substance_painter.ui
import substance_painter.js as spjs


PLUGIN_WIDGET = None
DOCK_WIDGET = None
TOOLBAR_BUTTON = None
UPDATE_CONTROLLER = None

PLUGIN_VERSION = "1.1.0"
UPDATE_REPOSITORY = "skazochnik3d/Bake-Manager"
UPDATE_API_URL = (
    "https://api.github.com/repos/"
    + UPDATE_REPOSITORY
    + "/releases/latest"
)
UPDATE_ASSET_NAME = "BakeManager.zip"
UPDATE_CHECK_DELAY_MS = 2500
UPDATE_DEFER_SECONDS = 24 * 60 * 60
UPDATE_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
UPDATE_MANAGED_FILES = (
    "__init__.py",
    "bake_manager.py",
    "Bake_Manager_Icon.png",
    "README_RU.txt",
)


# ----------------------------------------------------------------------
# Qt data roles
# ----------------------------------------------------------------------

ROLE_KIND = int(QtCore.Qt.ItemDataRole.UserRole)
ROLE_RESOURCE_URL = ROLE_KIND + 1
ROLE_ORIGINAL_NAME = ROLE_KIND + 2
ROLE_FOLDER_PATH = ROLE_KIND + 3
ROLE_DRAG_PATH = ROLE_KIND + 4
CUSTOM_ASSET_MIME = "application/x-custom-asset-manager"

COLOR_LABELS = {
    "none": None,
    "red": (
        QtGui.QColor("#ff8a8a"),
        QtGui.QColor("#d64242"),
        QtGui.QColor("#7f2020"),
    ),
    "orange": (
        QtGui.QColor("#ffc078"),
        QtGui.QColor("#e2762f"),
        QtGui.QColor("#884018"),
    ),
    "yellow": (
        QtGui.QColor("#fff19a"),
        QtGui.QColor("#d9b83e"),
        QtGui.QColor("#80691d"),
    ),
    "green": (
        QtGui.QColor("#a9ed9c"),
        QtGui.QColor("#55a94b"),
        QtGui.QColor("#2d6628"),
    ),
    "cyan": (
        QtGui.QColor("#92e8df"),
        QtGui.QColor("#3aa9a0"),
        QtGui.QColor("#21635f"),
    ),
    "blue": (
        QtGui.QColor("#91c5ff"),
        QtGui.QColor("#4388d4"),
        QtGui.QColor("#254f82"),
    ),
    "purple": (
        QtGui.QColor("#d2a5ff"),
        QtGui.QColor("#9147dc"),
        QtGui.QColor("#55258a"),
    ),
}

COLOR_LABEL_NAMES = {
    "none": "None",
    "red": "Red",
    "orange": "Orange",
    "yellow": "Yellow",
    "green": "Green",
    "cyan": "Cyan",
    "blue": "Blue",
    "purple": "Purple",
}

KIND_FOLDER = "folder"
KIND_RESOURCE = "resource"


# ----------------------------------------------------------------------
# Default folders
# ----------------------------------------------------------------------

DEFAULT_BAKE_FOLDER = "Bake Maps"
DEFAULT_IMPORTED_FOLDER = "Imported Textures"


BAKE_KEYWORDS = (
    "normal map from mesh",
    "ambient occlusion map from mesh",
    "world space normal",
    "worldspace normal",
    "curvature",
    "position map",
    "thickness",
    "id map",
)


# Image extensions we accept as on-disk previews.
PREVIEW_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tga",
    ".tif",
    ".tiff",
    ".exr",
    ".webp",
)


# Mesh map usage name -> source map name used by the export JSON config.
# Used to render real thumbnails for baked mesh maps via export_project_textures.
MESH_MAP_EXPORT_NAMES = {
    "AO": "ambient_occlusion",
    "BentNormals": "bent_normals",
    "Curvature": "curvature",
    "Height": "height",
    "ID": "id",
    "Normal": "normal_base",
    "Opacity": "opacity",
    "Position": "position",
    "Thickness": "thickness",
    "WorldSpaceNormal": "world_space_normals",
}


# Mesh map usage name -> short filename suffix.
# Example: Cube_N.png, Cube_AO.png, Cube_BN.png.
MESH_MAP_FILE_SUFFIXES = {
    "AO": "AO",
    "BentNormals": "BN",
    "Curvature": "C",
    "Height": "H",
    "ID": "ID",
    "Normal": "N",
    "Opacity": "O",
    "Position": "P",
    "Thickness": "T",
    "WorldSpaceNormal": "WSN",
}


# Bake Setup serialization. Mesh-file paths are intentionally project-specific
# and are not copied into reusable setups.
BAKE_SETUP_EXCLUDED_COMMON = {
    "HipolyMesh",
    "CageMesh",
    "OffsetMap",
    # Controlled separately. Painter expects (log2(width), log2(height)),
    # for example (11, 11) for 2048 x 2048.
    "OutputSize",
}

BAKE_SETUP_RESOLUTION_OPTIONS = (
    (256, "256"),
    (512, "512"),
    (1024, "1K"),
    (2048, "2K"),
    (4096, "4K"),
    (8192, "8K"),
)

BAKE_SETUP_AA_OPTIONS = (
    "1*1",
    "2*2",
    "4*4",
    "8*8",
)

BAKE_USAGE_LABELS = {
    "AO": "AO",
    "BentNormals": "BN",
    "Curvature": "C",
    "Height": "H",
    "ID": "ID",
    "Normal": "N",
    "Opacity": "O",
    "Position": "P",
    "Thickness": "T",
    "WorldSpaceNormal": "WSN",
}

BAKE_USAGE_TYPES = {
    "AO": "Ambient Occlusion",
    "BentNormals": "Bent Normals",
    "Curvature": "Curvature",
    "Height": "Height",
    "ID": "ID Map",
    "Normal": "Normal",
    "Opacity": "Opacity",
    "Position": "Position",
    "Thickness": "Thickness",
    "WorldSpaceNormal": "World Space Normal",
}


# ----------------------------------------------------------------------
# Folder tree
# ----------------------------------------------------------------------

class FolderTreeWidget(QtWidgets.QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setHeaderHidden(True)
        self.setMinimumWidth(150)
        self.setMaximumWidth(280)

        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )

        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )


# ----------------------------------------------------------------------
# Tile list
# ----------------------------------------------------------------------

class AssetTileListWidget(QtWidgets.QListWidget):
    """Painter-like tile view with drag-and-drop into Painter."""

    def manager_widget(self):
        """Find the actual AssetManagerWidget above this list.

        QWidget.window() returns Painter's QDockWidget, not our content widget.
        """
        current = self.parentWidget()

        while current is not None:
            if current.__class__.__name__ == "AssetManagerWidget":
                return current

            current = current.parentWidget()

        return None

    def __init__(self, parent=None):
        super().__init__(parent)

        self._drag_hover_kind = None
        self._drag_hover_position = None
        self._drag_hover_timer = QtCore.QTimer(self)
        self._drag_hover_timer.setInterval(60)
        self._drag_hover_timer.timeout.connect(
            self.track_drag_hover_target
        )

        self.setViewMode(
            QtWidgets.QListView.ViewMode.IconMode
        )

        self.setMovement(
            QtWidgets.QListView.Movement.Static
        )

        self.setResizeMode(
            QtWidgets.QListView.ResizeMode.Adjust
        )

        self.setFlow(
            QtWidgets.QListView.Flow.LeftToRight
        )

        self.setWrapping(True)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)

        self.setIconSize(
            QtCore.QSize(112, 112)
        )

        self.setGridSize(
            QtCore.QSize(124, 158)
        )

        self.setSpacing(4)
        self.setMinimumWidth(124)
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )

        self.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.DragOnly
        )
        self.setDefaultDropAction(
            QtCore.Qt.DropAction.CopyAction
        )

    def track_drag_hover_target(self):
        """Remember the last supported Painter panel under the cursor.

        QApplication.widgetAt() can return None after native QDrag.exec()
        finishes, so the target is sampled continuously while dragging.
        """
        manager = self.manager_widget()

        if manager is None:
            return

        global_position = QtGui.QCursor.pos()
        target = QtWidgets.QApplication.widgetAt(
            global_position
        )

        if target is None:
            return

        try:
            # Internal drop onto a folder tile in this manager.
            if (
                target is self
                or target is self.viewport()
                or self.isAncestorOf(target)
            ):
                local_position = self.viewport().mapFromGlobal(
                    global_position
                )
                hovered_item = self.itemAt(
                    local_position
                )

                if (
                    hovered_item is not None
                    and hovered_item.data(ROLE_KIND) == KIND_FOLDER
                    and hovered_item.text() != ".."
                ):
                    self._drag_hover_kind = "folder"
                    self._drag_hover_position = global_position
                    self._drag_folder_path = hovered_item.data(
                        ROLE_FOLDER_PATH
                    )
                    return

            if manager.is_layers_widget(target):
                self._drag_hover_kind = "layers"
                self._drag_hover_position = global_position
                return

        except RuntimeError:
            return

    def startDrag(self, supported_actions):
        items = self.selectedItems()

        if not items:
            return

        file_paths = []

        for item in items:
            path = item.data(ROLE_DRAG_PATH)

            if path and os.path.isfile(str(path)):
                file_paths.append(os.path.normpath(str(path)))

        if not file_paths:
            manager = self.manager_widget()

            if (
                manager is not None
                and hasattr(manager, "status_label")
            ):
                manager.status_label.setText(
                    "Select one or more texture tiles to drag."
                )

            return

        mime_data = QtCore.QMimeData()
        mime_data.setUrls(
            [
                QtCore.QUrl.fromLocalFile(path)
                for path in file_paths
            ]
        )
        mime_data.setText("\n".join(file_paths))

        payload = []

        for item in items:
            payload.append(
                {
                    "resource_url": item.data(ROLE_RESOURCE_URL),
                    "drag_path": item.data(ROLE_DRAG_PATH),
                    "text": item.text(),
                }
            )

        mime_data.setData(
            CUSTOM_ASSET_MIME,
            QtCore.QByteArray(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                ).encode("utf-8")
            ),
        )

        drag = QtGui.QDrag(self)
        drag.setMimeData(mime_data)

        current = self.currentItem() or items[0]
        icon = current.icon()

        if not icon.isNull():
            pixmap = icon.pixmap(self.iconSize())

            if not pixmap.isNull():
                drag.setPixmap(pixmap)
                drag.setHotSpot(
                    QtCore.QPoint(
                        pixmap.width() // 2,
                        pixmap.height() // 2,
                    )
                )

        self._drag_hover_kind = None
        self._drag_hover_position = None
        self._drag_folder_path = None
        self._drag_hover_timer.start()

        try:
            drag.exec(
                QtCore.Qt.DropAction.CopyAction,
                QtCore.Qt.DropAction.CopyAction,
            )
        finally:
            self._drag_hover_timer.stop()

        manager = self.manager_widget()

        if manager is None:
            return

        drop_kind = self._drag_hover_kind
        drop_position = (
            self._drag_hover_position
            or QtGui.QCursor.pos()
        )

        if (
            drop_kind == "folder"
            and self._drag_folder_path
        ):
            manager.move_items_to_folder(
                items,
                self._drag_folder_path,
            )
            return

        if drop_kind == "layers":
            manager.handle_drop_to_layers(
                items,
                drop_position,
            )
            return

        if hasattr(manager, "status_label"):
            manager.status_label.setText(
                "Drop target was not recognized. "
                "Release over the middle of Layers, Properties - Fill, "
                "or Texture Set Settings."
            )


# ----------------------------------------------------------------------
# Main widget
# ----------------------------------------------------------------------

class AssetManagerWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setObjectName("BakeManagerWidget")
        self.setWindowTitle("Bake Manager")
        self.setMinimumSize(145, 250)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        self._loading = False
        self._data = self.default_data()

        # The plugin can start before Painter finishes opening the project.
        # Keep the sidecar path that the current in-memory data was loaded from
        # and reload automatically when a project becomes available.
        self._loaded_project_data_path: Optional[str] = None

        # Shared BakeProject files may only be written after they have been
        # loaded for the current Painter scene. This prevents a short scene
        # transition from overwriting saved Setups with an empty Project.
        self._shared_projects_ready = False

        # Private Smart Materials are discovered from files in the plugin
        # root. Their Assets-library duplicates are cleaned only once after
        # Painter has finished building its UI.
        self._private_smart_material_cleanup_scheduled = False

        # Flat browser state: folders and textures share the same tile view.
        self._current_folder_path = ""

        # Quick map filter shown beside the search box.
        # Values: "", "N", "AO", "CV", "ID".
        self._active_suffix_filter = ""
        self.suffix_filter_buttons = {}

        # Cache of on-disk preview icons, keyed by (path, available).
        # Value is (mtime, QIcon) so we reload only when the file changes.
        self._preview_cache: dict[tuple[str, bool], tuple[float, QtGui.QIcon]] = {}

        self._last_mesh_map_signature: Optional[tuple] = None
        self._auto_export_running = False
        self._painter_was_busy = False

        self._bake_watch_timer = QtCore.QTimer(self)
        self._bake_watch_timer.setInterval(2500)
        self._bake_watch_timer.timeout.connect(
            self.check_for_new_bakes
        )

        self._marmoset_status_timer = QtCore.QTimer(self)
        self._marmoset_status_timer.setInterval(750)
        self._marmoset_status_timer.timeout.connect(
            self.check_marmoset_bridge_status
        )
        self._marmoset_status_path: Optional[str] = None
        self._marmoset_process = None
        self._last_marmoset_manifest_generation = None

        # Bake Setup state.
        # Resolution/AA row overrides were intentionally removed here:
        # they modified BakingParameters broadly and caused empty bakes.
        # Bake Setup now uses the last known-working capture/apply path.
        self._setup_row_checks = {}
        self._setup_row_widgets = {}
        self._setup_disabled_bakers = {}
        self._bake_setup_queue = []
        self._bake_setup_queue_index = -1
        self._bake_setup_running = False
        self._bake_setup_events_connected = False

        self.build_ui()
        self.connect_signals()
        self.load_manager()
        self.connect_bake_setup_events()
        self.refresh_bake_setup_ui()

        self._bake_watch_timer.start()
        QtCore.QTimer.singleShot(
            1200,
            self.initialize_bake_watcher,
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        search_row = QtWidgets.QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(3)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search assets...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(24)
        self.search_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        search_row.addWidget(
            self.search_edit,
            1,
        )

        filter_definitions = (
            (
                "N",
                "Normal maps",
            ),
            (
                "AO",
                "Ambient Occlusion maps",
            ),
            (
                "CV",
                "Curvature maps",
            ),
            (
                "ID",
                "ID maps",
            ),
        )

        for filter_key, tooltip in filter_definitions:
            button = QtWidgets.QToolButton(self)
            button.setText(filter_key)
            button.setToolTip(
                tooltip
                + "\nClick again to clear the filter."
            )
            button.setCheckable(True)
            button.setAutoRaise(False)
            button.setFixedHeight(24)
            button.setMinimumWidth(
                26 if len(filter_key) == 1 else 31
            )
            button.setCursor(
                QtCore.Qt.CursorShape.PointingHandCursor
            )
            button.setStyleSheet(
                "QToolButton {"
                " padding: 1px 5px;"
                " border: 1px solid #555;"
                " border-radius: 3px;"
                " background: #333;"
                "}"
                "QToolButton:hover {"
                " border-color: #777;"
                " background: #3d3d3d;"
                "}"
                "QToolButton:checked {"
                " border-color: #3f8fd8;"
                " background: #285d89;"
                " color: white;"
                "}"
            )
            # Painter/PySide may expose clicked() without the optional
            # boolean argument. Read the button state directly so the filter
            # works with either signal overload.
            button.clicked.connect(
                lambda *_args, key=filter_key, control=button: (
                    self.set_suffix_filter(
                        key,
                        control.isChecked(),
                    )
                )
            )
            self.suffix_filter_buttons[
                filter_key
            ] = button
            search_row.addWidget(button)

        main_layout.addLayout(search_row)

        self.breadcrumb_label = QtWidgets.QLabel("Project")
        self.breadcrumb_label.setMinimumWidth(0)
        self.breadcrumb_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        main_layout.addWidget(self.breadcrumb_label)

        self.asset_list = AssetTileListWidget(self)
        # Resizable vertical split between the asset browser and Bake Setup.
        self.main_splitter = QtWidgets.QSplitter(
            QtCore.Qt.Orientation.Vertical,
            self,
        )
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(7)
        self.main_splitter.setStyleSheet(
            "QSplitter::handle:vertical {"
            " background: #777;"
            " border-top: 1px solid #999;"
            " border-bottom: 1px solid #444;"
            " height: 7px;"
            "}"
            "QSplitter::handle:vertical:hover {"
            " background: #999;"
            "}"
        )

        self.asset_list.setMinimumHeight(100)
        self.main_splitter.addWidget(
            self.asset_list
        )

        self.build_bake_setup_panel(
            self.main_splitter
        )

        self.main_splitter.setStretchFactor(
            0,
            3,
        )
        self.main_splitter.setStretchFactor(
            1,
            1,
        )
        self.main_splitter.setSizes(
            [500, 240]
        )

        main_layout.addWidget(
            self.main_splitter,
            1,
        )

        self.status_label = QtWidgets.QLabel(
            "Right-click for options. Double-click folders to open them."
        )
        self.status_label.setMinimumWidth(0)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        main_layout.addWidget(self.status_label)

    def connect_signals(self):
        self.search_edit.textChanged.connect(
            self.populate_asset_tiles
        )

        self.asset_list.customContextMenuRequested.connect(
            self.show_asset_context_menu
        )

        self.asset_list.itemDoubleClicked.connect(
            self.on_asset_double_clicked
        )

    # ------------------------------------------------------------------
    # Bake Setup UI and project/setup storage
    # ------------------------------------------------------------------

    def build_bake_setup_panel(
        self,
        splitter: QtWidgets.QSplitter,
    ):
        self.bake_setup_frame = QtWidgets.QFrame(
            splitter
        )
        self.bake_setup_frame.setObjectName("BakeSetupFrame")
        self.bake_setup_frame.setMinimumHeight(155)
        self.bake_setup_frame.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.bake_setup_frame.setStyleSheet(
            "#BakeSetupFrame { border-top: 2px solid #8a8a8a; }"
        )

        layout = QtWidgets.QVBoxLayout(
            self.bake_setup_frame
        )
        layout.setContentsMargins(2, 5, 2, 2)
        layout.setSpacing(3)

        title = QtWidgets.QLabel("BAKE SETUP")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        project_row = QtWidgets.QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(3)

        project_label = QtWidgets.QLabel("Project")
        project_label.setMinimumWidth(48)
        project_row.addWidget(project_label)

        self.bake_project_combo = QtWidgets.QComboBox()
        self.bake_project_combo.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        project_row.addWidget(self.bake_project_combo, 1)

        self.new_bake_project_button = QtWidgets.QToolButton()
        self.new_bake_project_button.setText("+")
        self.new_bake_project_button.setToolTip("Create Bake Project")
        project_row.addWidget(self.new_bake_project_button)
        layout.addLayout(project_row)

        setup_header_row = QtWidgets.QHBoxLayout()
        setup_header_row.setContentsMargins(0, 0, 0, 0)
        setup_header_row.setSpacing(3)
        setup_header_row.addWidget(QtWidgets.QLabel("Setup"), 1)

        self.new_bake_setup_button = QtWidgets.QToolButton()
        self.new_bake_setup_button.setText("+")
        self.new_bake_setup_button.setToolTip(
            "Capture the current Mesh Map baking settings"
        )
        setup_header_row.addWidget(self.new_bake_setup_button)
        layout.addLayout(setup_header_row)

        self.bake_setup_list = QtWidgets.QListWidget()
        self.bake_setup_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.bake_setup_list.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.bake_setup_list.setMinimumHeight(60)
        self.bake_setup_list.setMaximumHeight(16777215)
        self.bake_setup_list.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(
            self.bake_setup_list,
            1,
        )

        self.bake_buttons_container = QtWidgets.QWidget(
            self.bake_setup_frame
        )
        self.bake_buttons_layout = QtWidgets.QBoxLayout(
            QtWidgets.QBoxLayout.Direction.LeftToRight,
            self.bake_buttons_container,
        )
        self.bake_buttons_layout.setContentsMargins(
            0,
            2,
            0,
            0,
        )
        self.bake_buttons_layout.setSpacing(4)

        self.bake_setups_button = QtWidgets.QPushButton("Bake")
        self.bake_setups_button.setToolTip(
            "Bake every checked Setup for every Texture Set"
        )
        self.bake_setups_button.setMinimumHeight(26)
        self.bake_setups_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.bake_buttons_layout.addWidget(
            self.bake_setups_button
        )

        self.clear_mesh_maps_button = QtWidgets.QPushButton(
            "Clear Mesh Maps"
        )
        self.clear_mesh_maps_button.setMinimumHeight(26)
        self.clear_mesh_maps_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.bake_buttons_layout.addWidget(
            self.clear_mesh_maps_button
        )

        self.bake_smart_material_button = QtWidgets.QToolButton()
        self.bake_smart_material_button.setText(
            "Smart Mat"
        )
        self.bake_smart_material_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.bake_smart_material_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.bake_smart_material_button.setMinimumHeight(26)
        self.bake_smart_material_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.bake_smart_material_button.setStyleSheet(
            "QToolButton::menu-indicator {"
            " image: none;"
            " width: 0px;"
            " subcontrol-position: none;"
            "}"
        )
        self.bake_buttons_layout.addWidget(
            self.bake_smart_material_button
        )

        layout.addWidget(
            self.bake_buttons_container
        )

        self._bake_buttons_vertical = None
        QtCore.QTimer.singleShot(
            0,
            self.update_bake_buttons_layout,
        )

        self.bake_setup_progress = QtWidgets.QProgressBar()
        self.bake_setup_progress.setRange(0, 100)
        self.bake_setup_progress.setValue(0)
        self.bake_setup_progress.setTextVisible(False)
        self.bake_setup_progress.setMaximumHeight(5)
        layout.addWidget(self.bake_setup_progress)

        splitter.addWidget(
            self.bake_setup_frame
        )

        self.bake_project_combo.currentTextChanged.connect(
            self.on_bake_project_changed
        )
        self.bake_project_combo.customContextMenuRequested.connect(
            self.show_bake_project_menu
        )
        self.new_bake_project_button.clicked.connect(
            self.create_bake_project
        )
        self.new_bake_setup_button.clicked.connect(
            self.capture_new_bake_setup
        )
        self.bake_setup_list.customContextMenuRequested.connect(
            self.show_bake_setup_menu
        )
        self.bake_setup_list.itemDoubleClicked.connect(
            lambda _item: self.apply_selected_bake_setup()
        )
        self.bake_setups_button.clicked.connect(
            self.start_bake_setup_queue
        )
        self.clear_mesh_maps_button.clicked.connect(
            self.clear_all_mesh_maps
        )
        self.restore_main_splitter_state()
        self.main_splitter.splitterMoved.connect(
            self.save_main_splitter_state
        )

    def update_bake_buttons_layout(self):
        """Stack the bottom actions when the dock becomes narrow."""
        if not hasattr(
            self,
            "bake_buttons_layout",
        ):
            return

        available_width = (
            self.bake_setup_frame
            .contentsRect()
            .width()
        )
        use_vertical = (
            available_width < 330
        )

        if (
            self._bake_buttons_vertical
            is use_vertical
        ):
            return

        self._bake_buttons_vertical = (
            use_vertical
        )

        direction = (
            QtWidgets.QBoxLayout.Direction.TopToBottom
            if use_vertical
            else QtWidgets.QBoxLayout.Direction.LeftToRight
        )
        self.bake_buttons_layout.setDirection(
            direction
        )

        buttons = (
            self.bake_setups_button,
            self.clear_mesh_maps_button,
            self.bake_smart_material_button,
        )

        for index, button in enumerate(
            buttons
        ):
            self.bake_buttons_layout.setStretch(
                index,
                0 if use_vertical else 1,
            )
            button.setMinimumWidth(
                0
            )
            button.setMaximumWidth(
                16777215
            )

        self.bake_setup_frame.setMinimumHeight(
            220 if use_vertical else 155
        )
        self.bake_buttons_container.updateGeometry()
        self.bake_setup_frame.updateGeometry()

    def resizeEvent(
        self,
        event: QtGui.QResizeEvent,
    ):
        super().resizeEvent(event)

        QtCore.QTimer.singleShot(
            0,
            self.update_bake_buttons_layout,
        )

    def splitter_settings(self):
        return QtCore.QSettings(
            "BakeManager",
            "PanelLayout",
        )

    def restore_main_splitter_state(self):
        state = self.splitter_settings().value(
            "main_splitter_state"
        )

        if state:
            try:
                self.main_splitter.restoreState(
                    state
                )
                return
            except Exception:
                traceback.print_exc()

        self.main_splitter.setSizes(
            [500, 240]
        )

    def save_main_splitter_state(
        self,
        _position: int = 0,
        _index: int = 0,
    ):
        settings = self.splitter_settings()
        settings.setValue(
            "main_splitter_state",
            self.main_splitter.saveState(),
        )
        settings.sync()

    def plugin_root_directory(self) -> str:
        return os.path.dirname(
            os.path.abspath(__file__)
        )

    def legacy_shared_bake_projects_path(self) -> str:
        return os.path.join(
            self.plugin_root_directory(),
            "bake_projects.json",
        )

    @staticmethod
    def safe_bake_project_file_name(
        value: str,
    ) -> str:
        safe_name = str(value).strip()

        for invalid_character in '<>:"/\\|?*':
            safe_name = safe_name.replace(
                invalid_character,
                "_",
            )

        safe_name = safe_name.rstrip(
            ". "
        )

        return safe_name or "Project"

    def bake_project_file_path(
        self,
        project_name: str,
    ) -> str:
        return os.path.join(
            self.plugin_root_directory(),
            (
                "BakeProject__"
                + self.safe_bake_project_file_name(
                    project_name
                )
                + ".json"
            ),
        )

    @staticmethod
    def normalized_shared_project(
        project_data: Any,
    ) -> dict[str, Any]:
        if not isinstance(
            project_data,
            dict,
        ):
            project_data = {}

        setups = project_data.get(
            "setups",
            {},
        )

        if not isinstance(
            setups,
            dict,
        ):
            setups = {}

        checked_setups = project_data.get(
            "checked_setups",
            [],
        )

        if not isinstance(
            checked_setups,
            list,
        ):
            checked_setups = []

        checked_setups = [
            str(name)
            for name in checked_setups
            if str(name) in setups
        ]

        return {
            "setups": json.loads(
                json.dumps(
                    setups,
                    ensure_ascii=False,
                )
            ),
            "smart_materials": {},
            "checked_setups": checked_setups,
        }

    def save_shared_bake_projects(
        self,
        show_error: bool = False,
    ) -> bool:
        """Write one portable JSON file per Bake Project."""
        projects = self.bake_manager_data().setdefault(
            "projects",
            {},
        )
        expected_paths = set()

        try:
            for project_name, project_data in projects.items():
                project_name = str(
                    project_name
                ).strip()

                if not project_name:
                    continue

                path = self.bake_project_file_path(
                    project_name
                )
                temporary_path = path + ".tmp"
                expected_paths.add(
                    os.path.normcase(
                        os.path.abspath(path)
                    )
                )
                normalized = (
                    self.normalized_shared_project(
                        project_data
                    )
                )
                normalized.pop(
                    "smart_materials",
                    None,
                )
                payload = {
                    "version": 2,
                    "format": (
                        "Bake Manager Project"
                    ),
                    "project_name": project_name,
                    "project": normalized,
                }

                with open(
                    temporary_path,
                    "w",
                    encoding="utf-8",
                ) as stream:
                    json.dump(
                        payload,
                        stream,
                        ensure_ascii=False,
                        indent=4,
                    )

                # Keep the previous valid version as a recovery copy.
                if os.path.isfile(
                    path
                ):
                    try:
                        shutil.copy2(
                            path,
                            path + ".bak",
                        )
                    except OSError:
                        pass

                os.replace(
                    temporary_path,
                    path,
                )

            # Files disappear automatically when a Project is deleted or
            # renamed in the UI.
            root = self.plugin_root_directory()

            for file_name in os.listdir(root):
                if (
                    not file_name.startswith(
                        "BakeProject__"
                    )
                    or not file_name.lower().endswith(
                        ".json"
                    )
                ):
                    continue

                path = os.path.join(
                    root,
                    file_name,
                )
                normalized_path = os.path.normcase(
                    os.path.abspath(path)
                )

                if normalized_path in expected_paths:
                    continue

                try:
                    os.remove(path)
                except OSError:
                    traceback.print_exc()

                backup_path = path + ".bak"

                if os.path.isfile(
                    backup_path
                ):
                    try:
                        os.remove(
                            backup_path
                        )
                    except OSError:
                        pass

            return True

        except OSError:
            traceback.print_exc()

            if (
                show_error
                and hasattr(
                    self,
                    "status_label",
                )
            ):
                self.status_label.setText(
                    "Could not save the Bake Project file."
                )

            return False

    def read_legacy_shared_bake_projects(
        self,
    ) -> dict[str, Any]:
        path = (
            self.legacy_shared_bake_projects_path()
        )

        if not os.path.isfile(path):
            return {}

        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as stream:
                payload = json.load(stream)
        except (
            OSError,
            json.JSONDecodeError,
        ):
            traceback.print_exc()
            return {}

        projects = payload.get(
            "projects",
            {},
        )

        if not isinstance(projects, dict):
            return {}

        return {
            str(name): (
                self.normalized_shared_project(
                    project
                )
            )
            for name, project in projects.items()
            if str(name).strip()
        }

    def read_shared_bake_projects(
        self,
    ) -> Optional[dict[str, Any]]:
        """Auto-load every BakeProject__*.json from the plugin root."""
        root = self.plugin_root_directory()
        normalized_projects = {}

        try:
            file_names = sorted(
                os.listdir(root),
                key=str.lower,
            )
        except OSError:
            file_names = []

        for file_name in file_names:
            if (
                not file_name.startswith(
                    "BakeProject__"
                )
                or not file_name.lower().endswith(
                    ".json"
                )
            ):
                continue

            path = os.path.join(
                root,
                file_name,
            )

            payload = None

            for candidate_path in (
                path,
                path + ".bak",
            ):
                if not os.path.isfile(
                    candidate_path
                ):
                    continue

                try:
                    with open(
                        candidate_path,
                        "r",
                        encoding="utf-8",
                    ) as stream:
                        candidate_payload = (
                            json.load(
                                stream
                            )
                        )

                    if isinstance(
                        candidate_payload,
                        dict,
                    ):
                        payload = (
                            candidate_payload
                        )
                        break

                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    continue

            if not isinstance(
                payload,
                dict,
            ):
                continue

            project_name = str(
                payload.get(
                    "project_name",
                    "",
                )
            ).strip()
            project_data = payload.get(
                "project",
                {},
            )

            if not project_name:
                project_name = os.path.splitext(
                    file_name[len(
                        "BakeProject__"
                    ):]
                )[0]

            if not project_name:
                continue

            normalized_projects[
                project_name
            ] = (
                self.normalized_shared_project(
                    project_data
                )
            )

        # Recover from the previous aggregate file. A non-empty legacy
        # Project is preferred when a newer per-Project file was accidentally
        # saved without Setups by an older plugin build.
        legacy_projects = (
            self.read_legacy_shared_bake_projects()
        )

        for project_name, legacy_project in (
            legacy_projects.items()
        ):
            current_project = normalized_projects.get(
                project_name
            )

            if (
                current_project is None
                or (
                    not current_project.get(
                        "setups"
                    )
                    and legacy_project.get(
                        "setups"
                    )
                )
            ):
                normalized_projects[
                    project_name
                ] = legacy_project

        if not normalized_projects:
            return None

        current_project = str(
            self._data.get(
                "bake_manager",
                {},
            ).get(
                "current_project",
                "",
            )
        )

        if current_project not in normalized_projects:
            current_project = next(
                iter(normalized_projects)
            )

        return {
            "projects": normalized_projects,
            "current_project": current_project,
        }

    def apply_shared_bake_projects(
        self,
        create_if_missing: bool = True,
    ) -> bool:
        """Load all Project files automatically and preserve Smart Mats."""
        shared_data = (
            self.read_shared_bake_projects()
        )
        manager_data = self._data.setdefault(
            "bake_manager",
            {
                "projects": {},
                "current_project": "Project",
            },
        )
        scene_projects = manager_data.setdefault(
            "projects",
            {},
        )

        if shared_data is None:
            if create_if_missing:
                self.save_shared_bake_projects()
            return False

        merged_projects = {}
        recovered_from_scene = False

        for project_name, shared_project in (
            shared_data[
                "projects"
            ].items()
        ):
            scene_project = scene_projects.get(
                project_name,
                {},
            )
            normalized = (
                self.normalized_shared_project(
                    shared_project
                )
            )
            scene_normalized = (
                self.normalized_shared_project(
                    scene_project
                )
            )

            # Recover Setups from the scene sidecar when an older plugin
            # version has already overwritten the shared file with an empty
            # Project. The recovered data is written back below.
            if (
                not normalized.get(
                    "setups"
                )
                and scene_normalized.get(
                    "setups"
                )
            ):
                normalized[
                    "setups"
                ] = scene_normalized[
                    "setups"
                ]
                normalized[
                    "checked_setups"
                ] = scene_normalized[
                    "checked_setups"
                ]
                recovered_from_scene = True

            normalized[
                "smart_materials"
            ] = dict(
                scene_project.get(
                    "smart_materials",
                    {},
                )
                if isinstance(
                    scene_project,
                    dict,
                )
                else {}
            )
            merged_projects[
                project_name
            ] = normalized

        # Preserve additional Projects found only in the current scene
        # sidecar, provided they actually contain saved Setups.
        for project_name, scene_project in (
            scene_projects.items()
        ):
            if project_name in merged_projects:
                continue

            scene_normalized = (
                self.normalized_shared_project(
                    scene_project
                )
            )

            if not scene_normalized.get(
                "setups"
            ):
                continue

            scene_normalized[
                "smart_materials"
            ] = dict(
                scene_project.get(
                    "smart_materials",
                    {},
                )
                if isinstance(
                    scene_project,
                    dict,
                )
                else {}
            )
            merged_projects[
                project_name
            ] = scene_normalized
            recovered_from_scene = True

        manager_data[
            "projects"
        ] = merged_projects
        manager_data[
            "current_project"
        ] = shared_data[
            "current_project"
        ]

        if (
            manager_data[
                "current_project"
            ]
            not in merged_projects
        ):
            manager_data[
                "current_project"
            ] = next(
                iter(
                    merged_projects
                )
            )

        if recovered_from_scene:
            self.save_shared_bake_projects(
                show_error=False
            )

        return True

    def reload_shared_bake_projects(
        self,
    ):
        """Internal automatic refresh; no file dialog is used."""
        loaded = self.apply_shared_bake_projects(
            create_if_missing=False
        )

        if not loaded:
            return

        self._setup_disabled_bakers.clear()
        self.refresh_bake_setup_ui()
        self.save_data()

    def bake_manager_data(self) -> dict[str, Any]:
        return self._data.setdefault(
            "bake_manager",
            {
                "projects": {
                    "Project": {
                        "setups": {},
                        "smart_materials": {},
                        "checked_setups": [],
                    }
                },
                "current_project": "Project",
            },
        )

    def current_bake_project_name(self) -> str:
        manager_data = self.bake_manager_data()
        projects = manager_data.setdefault("projects", {})

        if not projects:
            projects["Project"] = {
                "setups": {},
                "smart_materials": {},
                "checked_setups": [],
            }

        current = str(
            manager_data.get("current_project", "Project")
        )

        if current not in projects:
            current = next(iter(projects))
            manager_data["current_project"] = current

        return current

    def current_bake_project(self) -> dict[str, Any]:
        name = self.current_bake_project_name()
        project = self.bake_manager_data()["projects"].setdefault(
            name,
            {},
        )
        project.setdefault("setups", {})
        project.setdefault("smart_materials", {})
        project.setdefault("checked_setups", [])
        return project

    def import_legacy_bake_templates(self):
        """Manual migration helper for older bake_templates.json files."""
        project = self.current_bake_project()

        if project.get("setups"):
            return

        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bake_templates.json",
        )

        if not os.path.isfile(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, json.JSONDecodeError):
            traceback.print_exc()
            return

        templates = payload.get("templates", {})

        if isinstance(templates, dict) and templates:
            project["setups"] = dict(templates)
            project["checked_setups"] = list(templates)

    def refresh_bake_setup_ui(self):
        if not hasattr(self, "bake_project_combo"):
            return

        self.ensure_temporary_smart_material_ignore_rule()
        self.delete_stale_temporary_smart_material_resources()
        self.purge_bake_manager_temporary_spsm_files()
        self.scan_private_smart_materials()
        manager_data = self.bake_manager_data()
        projects = manager_data.setdefault("projects", {})

        if not projects:
            projects["Project"] = {
                "setups": {},
                "smart_materials": {},
                "checked_setups": [],
            }

        current = self.current_bake_project_name()

        self.bake_project_combo.blockSignals(True)
        self.bake_project_combo.clear()
        self.bake_project_combo.addItems(
            sorted(projects, key=str.lower)
        )
        index = self.bake_project_combo.findText(current)
        self.bake_project_combo.setCurrentIndex(
            index if index >= 0 else 0
        )
        self.bake_project_combo.blockSignals(False)

        self.refresh_bake_setup_list()
        self.refresh_smart_material_menu()

    def on_bake_project_changed(self, name: str):
        if not name:
            return

        manager_data = self.bake_manager_data()

        if name not in manager_data.get("projects", {}):
            return

        manager_data["current_project"] = name
        self._setup_disabled_bakers.clear()
        self.refresh_bake_setup_list()
        self.refresh_smart_material_menu()
        self.save_data()

    def create_bake_project(self):
        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "New Bake Project",
            "Project name:",
        )

        if not accepted:
            return

        name = str(name).strip()

        if not name:
            return

        projects = self.bake_manager_data().setdefault(
            "projects",
            {},
        )

        if name in projects:
            QtWidgets.QMessageBox.warning(
                self,
                "Bake Manager",
                "A project with this name already exists.",
            )
            return

        projects[name] = {
            "setups": {},
            "smart_materials": {},
            "checked_setups": [],
        }
        self.bake_manager_data()["current_project"] = name
        self.refresh_bake_setup_ui()
        self.save_data()

    def show_bake_project_menu(self, position):
        current = self.current_bake_project_name()
        menu = QtWidgets.QMenu(self)
        rename_action = menu.addAction(
            "Rename"
        )
        delete_action = menu.addAction(
            "Delete"
        )
        delete_action.setEnabled(
            len(
                self.bake_manager_data().get(
                    "projects",
                    {},
                )
            )
            > 1
        )

        chosen = menu.exec(
            self.bake_project_combo.mapToGlobal(
                position
            )
        )

        if chosen == rename_action:
            self.rename_bake_project(
                current
            )
        elif chosen == delete_action:
            self.delete_bake_project(
                current
            )

    def rename_bake_project(self, old_name: str):
        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Bake Project",
            "New project name:",
            text=old_name,
        )

        if not accepted:
            return

        new_name = str(new_name).strip()
        projects = self.bake_manager_data().get("projects", {})

        if (
            not new_name
            or new_name == old_name
            or new_name in projects
        ):
            return

        projects[new_name] = projects.pop(old_name)
        self.bake_manager_data()["current_project"] = new_name
        self.refresh_bake_setup_ui()
        self.save_data()

    def delete_bake_project(self, name: str):
        projects = self.bake_manager_data().get("projects", {})

        if len(projects) <= 1 or name not in projects:
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete Bake Project",
            f'Delete project "{name}" and all of its Setups?',
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )

        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        projects.pop(name, None)
        self.bake_manager_data()["current_project"] = next(
            iter(projects)
        )
        self.refresh_bake_setup_ui()
        self.save_data()

    def refresh_bake_setup_list(self):
        if not hasattr(self, "bake_setup_list"):
            return

        previous = self.selected_bake_setup_name()
        project = self.current_bake_project()
        setups = project.setdefault("setups", {})
        stored_checked = set(
            project.get("checked_setups", [])
        )

        self._setup_row_checks = {}
        self._setup_row_widgets = {}
        self.bake_setup_list.clear()

        for name in sorted(setups, key=str.lower):
            item = QtWidgets.QListWidgetItem()
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole,
                name,
            )
            widget = self.build_bake_setup_row(
                name,
                setups[name],
                checked=(
                    name in stored_checked
                    if project.get("checked_setups") is not None
                    else True
                ),
            )
            item.setSizeHint(widget.sizeHint())
            self.bake_setup_list.addItem(item)
            self.bake_setup_list.setItemWidget(item, widget)

            if name == previous:
                self.bake_setup_list.setCurrentItem(item)

    @staticmethod
    def bake_resolution_to_log2(
        pixels: int,
    ) -> int:
        """Painter OutputSize uses log2 values: 2048 -> 11."""
        pixels = max(
            1,
            int(
                pixels
            ),
        )
        return int(
            round(
                math.log2(
                    pixels
                )
            )
        )

    @staticmethod
    def bake_log2_to_resolution(
        value: Any,
    ) -> Optional[int]:
        try:
            exponent = int(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

        if not (
            1
            <= exponent
            <= 16
        ):
            return None

        return 1 << exponent

    @staticmethod
    def compact_bake_aa_label(
        value: Any,
    ) -> str:
        label = str(
            value
            or ""
        ).strip()

        match = re.search(
            r"(\d+)\s*[xX*×]\s*(\d+)",
            label,
        )

        if match:
            return (
                match.group(1)
                + "*"
                + match.group(2)
            )

        if label.lower() in {
            "none",
            "off",
            "disabled",
            "no subsampling",
        }:
            return "1*1"

        return ""

    @staticmethod
    def exact_common_property(
        common_props: dict[str, Any],
        normalized_target: str,
    ):
        """Return only an exact normalized property name; never fuzzy-match."""
        for short_name, prop in common_props.items():
            normalized = re.sub(
                r"[^a-z0-9]+",
                "",
                str(
                    short_name
                ).lower(),
            )

            if normalized == normalized_target:
                return short_name, prop

        return None, None

    def captured_setup_resolution(
        self,
        setup: dict[str, Any],
    ) -> int:
        stored = setup.get(
            "output_resolution"
        )

        try:
            stored = int(
                stored
            )
        except (
            TypeError,
            ValueError,
        ):
            stored = 0

        valid = {
            resolution
            for resolution, _label
            in BAKE_SETUP_RESOLUTION_OPTIONS
        }

        if stored in valid:
            return stored

        # Migration for Setups created before OutputSize was excluded.
        common = setup.get(
            "common",
            {},
        )

        if isinstance(
            common,
            dict,
        ):
            for short_name, entry in common.items():
                normalized = re.sub(
                    r"[^a-z0-9]+",
                    "",
                    str(
                        short_name
                    ).lower(),
                )

                if (
                    normalized != "outputsize"
                    or not isinstance(
                        entry,
                        dict,
                    )
                ):
                    continue

                value = entry.get(
                    "value"
                )

                if (
                    isinstance(
                        value,
                        list,
                    )
                    and value
                ):
                    resolution = (
                        self.bake_log2_to_resolution(
                            value[0]
                        )
                    )

                    if resolution in valid:
                        return resolution

        return 2048

    def captured_setup_antialiasing(
        self,
        setup: dict[str, Any],
    ) -> str:
        stored = self.compact_bake_aa_label(
            setup.get(
                "antialiasing",
                "",
            )
        )

        if stored in BAKE_SETUP_AA_OPTIONS:
            return stored

        common = setup.get(
            "common",
            {},
        )

        if isinstance(
            common,
            dict,
        ):
            for short_name, entry in common.items():
                normalized = re.sub(
                    r"[^a-z0-9]+",
                    "",
                    str(
                        short_name
                    ).lower(),
                )

                if (
                    normalized != "subsampling"
                    or not isinstance(
                        entry,
                        dict,
                    )
                ):
                    continue

                label = self.compact_bake_aa_label(
                    entry.get(
                        "enum",
                        "",
                    )
                )

                if label in BAKE_SETUP_AA_OPTIONS:
                    return label

        return "1*1"

    def save_bake_setup_resolution(
        self,
        setup_name: str,
        pixels: int,
    ):
        setup = (
            self.current_bake_project()
            .setdefault(
                "setups",
                {},
            )
            .get(
                setup_name
            )
        )

        if not isinstance(
            setup,
            dict,
        ):
            return

        setup[
            "output_resolution"
        ] = int(
            pixels
        )
        self.save_data()

    def save_bake_setup_antialiasing(
        self,
        setup_name: str,
        label: str,
    ):
        setup = (
            self.current_bake_project()
            .setdefault(
                "setups",
                {},
            )
            .get(
                setup_name
            )
        )

        if not isinstance(
            setup,
            dict,
        ):
            return

        compact = (
            self.compact_bake_aa_label(
                label
            )
        )

        if compact not in BAKE_SETUP_AA_OPTIONS:
            return

        setup[
            "antialiasing"
        ] = compact
        self.save_data()

    def make_bake_setup_resolution_combo(
        self,
        setup_name: str,
        setup: dict[str, Any],
    ) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setFixedWidth(
            58
        )

        for pixels, label in BAKE_SETUP_RESOLUTION_OPTIONS:
            combo.addItem(
                label,
                pixels,
            )

        current = (
            self.captured_setup_resolution(
                setup
            )
        )
        index = combo.findData(
            current
        )
        combo.setCurrentIndex(
            index
            if index >= 0
            else combo.findData(
                2048
            )
        )
        combo.setToolTip(
            "Output size for this Setup"
        )
        combo.currentIndexChanged.connect(
            lambda _index, n=setup_name, c=combo: (
                self.save_bake_setup_resolution(
                    n,
                    int(
                        c.currentData()
                    ),
                )
            )
        )
        return combo

    def make_bake_setup_aa_combo(
        self,
        setup_name: str,
        setup: dict[str, Any],
    ) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setFixedWidth(
            48
        )
        combo.addItems(
            list(
                BAKE_SETUP_AA_OPTIONS
            )
        )

        current = (
            self.captured_setup_antialiasing(
                setup
            )
        )
        index = combo.findText(
            current,
            QtCore.Qt.MatchFlag.MatchFixedString,
        )
        combo.setCurrentIndex(
            index
            if index >= 0
            else 0
        )
        combo.setToolTip(
            "Antialiasing for this Setup"
        )
        combo.currentTextChanged.connect(
            lambda value, n=setup_name: (
                self.save_bake_setup_antialiasing(
                    n,
                    value,
                )
            )
        )
        return combo

    def exact_subsampling_enum_value(
        self,
        prop,
        selected_label: str,
    ):
        """Map 1*1...8*8 through SubSampling's own enum table only."""
        selected = (
            self.compact_bake_aa_label(
                selected_label
            )
        )

        if selected not in BAKE_SETUP_AA_OPTIONS:
            return None

        try:
            enums = prop.enum_values() or {}
        except Exception:
            enums = {}

        for label, enum_value in enums.items():
            compact = (
                self.compact_bake_aa_label(
                    label
                )
            )

            if compact == selected:
                return enum_value

            if (
                selected == "1*1"
                and str(
                    label
                ).strip().lower()
                in {
                    "none",
                    "off",
                    "disabled",
                    "no subsampling",
                }
            ):
                return enum_value

        return None

    def append_bake_setup_quality_values(
        self,
        setup: dict[str, Any],
        common_props: dict[str, Any],
        values_to_set: dict[Any, Any],
    ):
        """Apply exactly OutputSize and SubSampling, using Painter's formats."""
        resolution = (
            self.captured_setup_resolution(
                setup
            )
        )
        _name, output_size_prop = (
            self.exact_common_property(
                common_props,
                "outputsize",
            )
        )

        if output_size_prop is not None:
            exponent = (
                self.bake_resolution_to_log2(
                    resolution
                )
            )
            values_to_set[
                output_size_prop
            ] = (
                exponent,
                exponent,
            )

        aa_label = (
            self.captured_setup_antialiasing(
                setup
            )
        )
        _name, subsampling_prop = (
            self.exact_common_property(
                common_props,
                "subsampling",
            )
        )

        if subsampling_prop is not None:
            enum_value = (
                self.exact_subsampling_enum_value(
                    subsampling_prop,
                    aa_label,
                )
            )

            if enum_value is not None:
                values_to_set[
                    subsampling_prop
                ] = enum_value

    def build_bake_setup_row(
        self,
        name: str,
        setup: dict[str, Any],
        checked: bool,
    ) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(
            1,
            1,
            1,
            1,
        )
        layout.setSpacing(
            2
        )

        active_check = QtWidgets.QCheckBox()
        active_check.setChecked(checked)
        active_check.setToolTip("Include this Setup in the bake queue")
        active_check.toggled.connect(
            lambda _checked: self.save_checked_bake_setups()
        )
        layout.addWidget(active_check)

        label = QtWidgets.QLabel(
            name
        )
        label.setFixedWidth(
            100
        )
        label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        label.setToolTip(
            name
        )
        layout.addWidget(
            label
        )

        resolution_combo = (
            self.make_bake_setup_resolution_combo(
                name,
                setup,
            )
        )
        layout.addWidget(
            resolution_combo
        )

        aa_combo = (
            self.make_bake_setup_aa_combo(
                name,
                setup,
            )
        )
        layout.addWidget(
            aa_combo
        )

        disabled = self._setup_disabled_bakers.setdefault(
            name,
            set(),
        )

        for usage_name in setup.get("enabled_bakers", []):
            chip = QtWidgets.QToolButton()
            chip.setText(
                BAKE_USAGE_LABELS.get(usage_name, usage_name)
            )
            chip.setCheckable(True)
            chip.setChecked(usage_name not in disabled)
            chip.setToolTip(
                f"{usage_name}: enable or disable for this session"
            )
            chip.toggled.connect(
                lambda enabled, n=name, u=usage_name: (
                    self.toggle_setup_baker(n, u, enabled)
                )
            )
            layout.addWidget(chip)

        # Keep every control packed against the left edge. Extra width is
        # consumed only after the map buttons, never between the Setup name
        # and the resolution selector.
        layout.addStretch(
            1
        )

        self._setup_row_checks[name] = active_check
        self._setup_row_widgets[name] = widget
        return widget

    def toggle_setup_baker(
        self,
        setup_name: str,
        usage_name: str,
        enabled: bool,
    ):
        disabled = self._setup_disabled_bakers.setdefault(
            setup_name,
            set(),
        )

        if enabled:
            disabled.discard(usage_name)
        else:
            disabled.add(usage_name)

    def save_checked_bake_setups(self):
        project = self.current_bake_project()
        project["checked_setups"] = [
            name
            for name, check in self._setup_row_checks.items()
            if check.isChecked()
        ]
        self.save_data()

    def selected_bake_setup_name(self) -> Optional[str]:
        if not hasattr(self, "bake_setup_list"):
            return None

        item = self.bake_setup_list.currentItem()

        if item is None:
            return None

        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def show_bake_setup_menu(self, position):
        item = self.bake_setup_list.itemAt(position)

        # The "+" button creates a new Setup. The context menu is reserved
        # for operations on an existing Setup.
        if item is None:
            return

        self.bake_setup_list.setCurrentItem(item)
        name = item.data(
            QtCore.Qt.ItemDataRole.UserRole
        )

        menu = QtWidgets.QMenu(self)
        apply_action = menu.addAction(
            "Apply to Active Texture Set"
        )
        rerecord_action = menu.addAction(
            "Re-record from Current Settings"
        )
        rename_action = menu.addAction(
            "Rename"
        )
        duplicate_action = menu.addAction(
            "Duplicate"
        )
        delete_action = menu.addAction(
            "Delete"
        )

        chosen = menu.exec(
            self.bake_setup_list.viewport().mapToGlobal(
                position
            )
        )

        if chosen == apply_action:
            self.apply_selected_bake_setup()
        elif chosen == rerecord_action:
            self.rerecord_bake_setup(name)
        elif chosen == rename_action:
            self.rename_bake_setup(name)
        elif chosen == duplicate_action:
            self.duplicate_bake_setup(name)
        elif chosen == delete_action:
            self.delete_bake_setup(name)

    @staticmethod
    def bake_property_to_entry(prop) -> Optional[dict[str, Any]]:
        try:
            value = prop.value()
        except Exception:
            return None

        entry = {}

        if isinstance(value, tuple):
            entry["value"] = list(value)
            entry["tuple"] = True
        elif isinstance(value, (bool, int, float, str)):
            entry["value"] = value
        else:
            return None

        try:
            enums = prop.enum_values()
        except Exception:
            enums = {}

        if enums:
            for label, enum_value in enums.items():
                if enum_value == value:
                    entry["enum"] = label
                    break

        return entry

    @staticmethod
    def bake_entry_to_value(prop, entry: dict[str, Any]):
        value = entry.get("value")

        if entry.get("tuple") and isinstance(value, list):
            value = tuple(value)

        enum_label = entry.get("enum")

        if enum_label:
            try:
                enum_value = prop.enum_value(enum_label)

                if enum_value is not None:
                    value = enum_value
            except Exception:
                pass

        return value

    def capture_bake_setup(
        self,
        texture_set_name: str,
    ) -> Optional[dict[str, Any]]:
        try:
            params = (
                substance_painter.baking.BakingParameters
                .from_texture_set_name(texture_set_name)
            )
        except Exception:
            traceback.print_exc()
            return None

        setup = {
            "common": {},
            "bakers": {},
            "enabled_bakers": [],
            "curvature_method": None,
        }

        try:
            for short_name, prop in params.common().items():
                normalized_name = re.sub(
                    r"[^a-z0-9]+",
                    "",
                    str(
                        short_name
                    ).lower(),
                )

                if normalized_name == "outputsize":
                    try:
                        output_value = prop.value()
                    except Exception:
                        output_value = None

                    if (
                        isinstance(
                            output_value,
                            tuple,
                        )
                        and output_value
                    ):
                        pixels = (
                            self.bake_log2_to_resolution(
                                output_value[0]
                            )
                        )

                        if pixels is not None:
                            setup[
                                "output_resolution"
                            ] = pixels

                    continue

                if short_name in BAKE_SETUP_EXCLUDED_COMMON:
                    continue

                entry = self.bake_property_to_entry(
                    prop
                )

                if entry is not None:
                    setup[
                        "common"
                    ][short_name] = entry

                    if normalized_name == "subsampling":
                        compact = (
                            self.compact_bake_aa_label(
                                entry.get(
                                    "enum",
                                    "",
                                )
                            )
                        )

                        if compact:
                            setup[
                                "antialiasing"
                            ] = compact
        except Exception:
            traceback.print_exc()

        usage_members = (
            substance_painter.textureset.MeshMapUsage.__members__
        )

        for usage_name, usage in usage_members.items():
            try:
                baker_props = params.baker(usage)
            except Exception:
                continue

            entries = {}

            for short_name, prop in baker_props.items():
                entry = self.bake_property_to_entry(prop)

                if entry is not None:
                    entries[short_name] = entry

            if entries:
                setup["bakers"][usage_name] = entries

        try:
            enabled = params.get_enabled_bakers()
            setup["enabled_bakers"] = [
                name
                for name, usage in usage_members.items()
                if usage in enabled
            ]
        except Exception:
            traceback.print_exc()

        try:
            method = params.get_curvature_method()

            for name, value in (
                substance_painter.baking.CurvatureMethod
                .__members__.items()
            ):
                if value == method:
                    setup["curvature_method"] = name
                    break
        except Exception:
            traceback.print_exc()

        return setup

    def active_bake_texture_set_name(self) -> Optional[str]:
        try:
            texture_set = self.active_texture_set_object()
            value = getattr(texture_set, "name", None)

            if isinstance(value, str):
                return value

            if callable(value):
                return str(value())
        except Exception:
            pass

        names = self.texture_set_names_for_bridge()
        return names[0] if names else None

    def capture_new_bake_setup(self):
        if not substance_painter.project.is_open():
            self.status_label.setText("Open a Painter project first.")
            return

        texture_set_name = self.active_bake_texture_set_name()

        if not texture_set_name:
            self.status_label.setText("No Texture Set is available.")
            return

        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "New Bake Setup",
            f"Setup name (captured from {texture_set_name}):",
        )

        if not accepted:
            return

        name = str(name).strip()

        if not name:
            return

        setup = self.capture_bake_setup(texture_set_name)

        if setup is None:
            self.status_label.setText(
                "Could not capture the current bake settings."
            )
            return

        project = self.current_bake_project()
        project.setdefault("setups", {})[name] = setup
        checked = project.setdefault("checked_setups", [])

        if name not in checked:
            checked.append(name)

        self.refresh_bake_setup_list()
        self.save_data()
        self.status_label.setText(f'Bake Setup saved: "{name}".')

    def rerecord_bake_setup(self, name: str):
        texture_set_name = self.active_bake_texture_set_name()

        if not texture_set_name:
            return

        previous_setup = (
            self.current_bake_project()
            .setdefault(
                "setups",
                {},
            )
            .get(
                name,
                {},
            )
        )
        setup = self.capture_bake_setup(
            texture_set_name
        )

        if setup is None:
            return

        for key in (
            "output_resolution",
            "antialiasing",
        ):
            if (
                key not in setup
                and key in previous_setup
            ):
                setup[
                    key
                ] = previous_setup[
                    key
                ]

        self.current_bake_project().setdefault("setups", {})[name] = setup
        self._setup_disabled_bakers.pop(name, None)
        self.refresh_bake_setup_list()
        self.save_data()
        self.status_label.setText(f'Re-recorded Setup "{name}".')

    def rename_bake_setup(self, old_name: str):
        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Bake Setup",
            "New Setup name:",
            text=old_name,
        )

        if not accepted:
            return

        new_name = str(new_name).strip()
        project = self.current_bake_project()
        setups = project.setdefault("setups", {})

        if (
            not new_name
            or new_name == old_name
            or new_name in setups
        ):
            return

        setups[new_name] = setups.pop(old_name)
        project["checked_setups"] = [
            new_name if name == old_name else name
            for name in project.get("checked_setups", [])
        ]

        if old_name in self._setup_disabled_bakers:
            self._setup_disabled_bakers[new_name] = (
                self._setup_disabled_bakers.pop(old_name)
            )

        self.refresh_bake_setup_list()
        self.save_data()

    def duplicate_bake_setup(self, name: str):
        setups = self.current_bake_project().setdefault("setups", {})

        if name not in setups:
            return

        base = name + " Copy"
        new_name = base
        counter = 2

        while new_name in setups:
            new_name = f"{base} {counter}"
            counter += 1

        setups[new_name] = json.loads(json.dumps(setups[name]))
        self.current_bake_project().setdefault(
            "checked_setups", []
        ).append(new_name)
        self.refresh_bake_setup_list()
        self.save_data()

    def delete_bake_setup(self, name: str):
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete Bake Setup",
            f'Delete Setup "{name}"?',
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )

        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        project = self.current_bake_project()
        project.setdefault("setups", {}).pop(name, None)
        project["checked_setups"] = [
            value
            for value in project.get("checked_setups", [])
            if value != name
        ]
        self._setup_disabled_bakers.pop(name, None)
        self.refresh_bake_setup_list()
        self.save_data()

    def apply_bake_setup(
        self,
        texture_set_name: str,
        setup: dict[str, Any],
        active_bakers: Optional[list[str]] = None,
    ) -> bool:
        try:
            params = (
                substance_painter.baking.BakingParameters
                .from_texture_set_name(texture_set_name)
            )
            common_props = params.common()
        except Exception:
            traceback.print_exc()
            return False

        values_to_set = {}

        for short_name, entry in setup.get("common", {}).items():
            if short_name in BAKE_SETUP_EXCLUDED_COMMON:
                continue

            prop = common_props.get(short_name)

            if prop is not None:
                values_to_set[prop] = self.bake_entry_to_value(
                    prop,
                    entry,
                )

        # OutputSize is a log2 tuple and SubSampling is resolved through
        # the exact enum table of Painter's own property.
        self.append_bake_setup_quality_values(
            setup,
            common_props,
            values_to_set,
        )

        usage_members = (
            substance_painter.textureset.MeshMapUsage.__members__
        )

        for usage_name, baker_entries in setup.get("bakers", {}).items():
            usage = usage_members.get(usage_name)

            if usage is None:
                continue

            try:
                baker_props = params.baker(usage)
            except Exception:
                continue

            for short_name, entry in baker_entries.items():
                prop = baker_props.get(short_name)

                if prop is not None:
                    values_to_set[prop] = self.bake_entry_to_value(
                        prop,
                        entry,
                    )

        try:
            if values_to_set:
                substance_painter.baking.BakingParameters.set(
                    values_to_set
                )
        except Exception:
            traceback.print_exc()
            return False

        try:
            enabled_names = (
                active_bakers
                if active_bakers is not None
                else setup.get("enabled_bakers", [])
            )
            enabled = [
                usage_members[name]
                for name in enabled_names
                if name in usage_members
            ]
            params.set_enabled_bakers(enabled)
        except Exception:
            traceback.print_exc()

        try:
            method_name = setup.get("curvature_method")

            if method_name:
                method = (
                    substance_painter.baking.CurvatureMethod
                    .__members__.get(method_name)
                )

                if method is not None:
                    params.set_curvature_method(method)
        except Exception:
            traceback.print_exc()

        return True

    def apply_selected_bake_setup(self):
        setup_name = self.selected_bake_setup_name()
        texture_set_name = self.active_bake_texture_set_name()

        if not setup_name or not texture_set_name:
            return

        setup = self.current_bake_project().get("setups", {}).get(
            setup_name
        )

        if setup is None:
            return

        disabled = self._setup_disabled_bakers.get(setup_name, set())
        active_bakers = [
            usage
            for usage in setup.get("enabled_bakers", [])
            if usage not in disabled
        ]

        if self.apply_bake_setup(
            texture_set_name,
            setup,
            active_bakers,
        ):
            self.status_label.setText(
                f'Applied "{setup_name}" to {texture_set_name}.'
            )

    # ------------------------------------------------------------------
    # Bake Setup queue
    # ------------------------------------------------------------------

    def connect_bake_setup_events(self):
        if self._bake_setup_events_connected:
            return

        try:
            dispatcher = substance_painter.event.DISPATCHER
            dispatcher.connect(
                substance_painter.event.BakingProcessEnded,
                self.on_bake_setup_process_ended,
            )
            dispatcher.connect(
                substance_painter.event.BakingProcessProgress,
                self.on_bake_setup_process_progress,
            )
            dispatcher.connect(
                substance_painter.event.ProjectEditionEntered,
                self.on_bake_manager_project_ready,
            )
            self._bake_setup_events_connected = True
        except Exception:
            traceback.print_exc()

    def disconnect_bake_setup_events(self):
        if not self._bake_setup_events_connected:
            return

        try:
            dispatcher = substance_painter.event.DISPATCHER
            dispatcher.disconnect(
                substance_painter.event.BakingProcessEnded,
                self.on_bake_setup_process_ended,
            )
            dispatcher.disconnect(
                substance_painter.event.BakingProcessProgress,
                self.on_bake_setup_process_progress,
            )
            dispatcher.disconnect(
                substance_painter.event.ProjectEditionEntered,
                self.on_bake_manager_project_ready,
            )
        except Exception:
            pass

        self._bake_setup_events_connected = False

    def on_bake_manager_project_ready(self, _event=None):
        QtCore.QTimer.singleShot(
            300,
            self.load_manager,
        )

    def build_bake_setup_queue(self) -> list[dict[str, Any]]:
        project = self.current_bake_project()
        setups = project.get("setups", {})
        checked = [
            name
            for name, check in self._setup_row_checks.items()
            if check.isChecked() and name in setups
        ]
        texture_sets = self.texture_set_names_for_bridge()
        queue = []

        for texture_set_name in texture_sets:
            for setup_name in checked:
                setup = setups[setup_name]
                disabled = self._setup_disabled_bakers.get(
                    setup_name,
                    set(),
                )
                active_bakers = [
                    usage
                    for usage in setup.get("enabled_bakers", [])
                    if usage not in disabled
                ]

                if active_bakers:
                    queue.append(
                        {
                            "set": texture_set_name,
                            "setup": setup_name,
                            "active_bakers": active_bakers,
                            "status": "pending",
                        }
                    )

        return queue

    def start_bake_setup_queue(self):
        if self._bake_setup_running:
            return

        if not substance_painter.project.is_open():
            self.status_label.setText("Open a Painter project first.")
            return

        queue = self.build_bake_setup_queue()

        if not queue:
            self.status_label.setText(
                "Check at least one Setup containing an enabled map."
            )
            return

        self._bake_setup_queue = queue
        self._bake_setup_queue_index = -1
        self._bake_setup_running = True
        self.bake_setups_button.setEnabled(False)
        self.clear_mesh_maps_button.setEnabled(False)
        self.bake_setup_progress.setValue(0)
        self.advance_bake_setup_queue()

    def advance_bake_setup_queue(self):
        if not self._bake_setup_running:
            return

        next_index = -1

        for index, entry in enumerate(self._bake_setup_queue):
            if entry["status"] == "pending":
                next_index = index
                break

        if next_index < 0:
            self.finish_bake_setup_queue()
            return

        self._bake_setup_queue_index = next_index
        entry = self._bake_setup_queue[next_index]
        setup = self.current_bake_project().get("setups", {}).get(
            entry["setup"]
        )

        if setup is None:
            entry["status"] = "missing"
            QtCore.QTimer.singleShot(0, self.advance_bake_setup_queue)
            return

        if not self.apply_bake_setup(
            entry["set"],
            setup,
            entry["active_bakers"],
        ):
            entry["status"] = "apply failed"
            QtCore.QTimer.singleShot(0, self.advance_bake_setup_queue)
            return

        try:
            texture_set = (
                substance_painter.textureset.TextureSet.from_name(
                    entry["set"]
                )
            )
            substance_painter.baking.bake_async(texture_set)
        except Exception:
            traceback.print_exc()
            entry["status"] = "launch failed"
            QtCore.QTimer.singleShot(0, self.advance_bake_setup_queue)
            return

        entry["status"] = "baking"
        self.status_label.setText(
            "Baking {0}/{1}: {2} / {3}".format(
                next_index + 1,
                len(self._bake_setup_queue),
                entry["set"],
                entry["setup"],
            )
        )

    def on_bake_setup_process_progress(self, event):
        if not self._bake_setup_running:
            return

        try:
            total = len(self._bake_setup_queue) or 1
            index = max(0, self._bake_setup_queue_index)
            overall = (index + float(event.progress)) / total
            self.bake_setup_progress.setValue(
                int(max(0.0, min(1.0, overall)) * 100)
            )
        except Exception:
            pass

    def on_bake_setup_process_ended(self, event):
        if not self._bake_setup_running:
            return

        if not (
            0 <= self._bake_setup_queue_index
            < len(self._bake_setup_queue)
        ):
            return

        entry = self._bake_setup_queue[
            self._bake_setup_queue_index
        ]
        success = (
            event.status
            == substance_painter.baking.BakingStatus.Success
        )

        if success:
            entry["status"] = "exporting"
            QtCore.QTimer.singleShot(
                150,
                lambda current=entry: self.finish_bake_setup_entry(
                    current
                ),
            )
        else:
            entry["status"] = "failed"
            QtCore.QTimer.singleShot(0, self.advance_bake_setup_queue)

    def finish_bake_setup_entry(self, entry: dict[str, Any]):
        try:
            substance_painter.ui.switch_to_mode(
                substance_painter.ui.UIMode.Edition
            )
        except Exception:
            pass

        try:
            made = self.export_bake_setup_variants(entry)
            entry["status"] = "done" if made else "export failed"
        except Exception:
            traceback.print_exc()
            entry["status"] = "export failed"

        self.bake_setup_progress.setValue(
            int(
                100
                * (self._bake_setup_queue_index + 1)
                / max(1, len(self._bake_setup_queue))
            )
        )
        QtCore.QTimer.singleShot(0, self.advance_bake_setup_queue)

    @staticmethod
    def safe_bake_name(value: str) -> str:
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
        return value.strip("._-") or "Setup"

    def bake_setup_resource_url(self, file_path: str) -> str:
        return "bakesetup+" + QtCore.QUrl.fromLocalFile(
            os.path.abspath(file_path)
        ).toString(
            QtCore.QUrl.ComponentFormattingOption.FullyEncoded
        )

    @staticmethod
    def normalized_resource_name(
        value: Any,
    ) -> str:
        return str(value or "").strip().lower()

    def collect_source_resource_identity(
        self,
        value: Any,
        depth: int = 0,
    ) -> tuple[set[str], set[str]]:
        """Extract ResourceID URLs and names from a Painter source object."""
        urls = set()
        names = set()

        if value is None or depth > 3:
            return urls, names

        if isinstance(
            value,
            substance_painter.resource.ResourceID,
        ):
            try:
                urls.add(value.url())
            except Exception:
                pass

            try:
                names.add(
                    self.normalized_resource_name(
                        value.name
                    )
                )
            except Exception:
                pass

            return urls, names

        for member_name in (
            "identifier",
            "resource_id",
            "resource_identifier",
            "resource",
            "get_resource",
            "get_resource_id",
        ):
            member = getattr(
                value,
                member_name,
                None,
            )

            if member is None:
                continue

            try:
                nested_value = (
                    member()
                    if callable(member)
                    else member
                )
            except Exception:
                continue

            if nested_value is value:
                continue

            nested_urls, nested_names = (
                self.collect_source_resource_identity(
                    nested_value,
                    depth + 1,
                )
            )
            urls.update(nested_urls)
            names.update(nested_names)

        for member_name in (
            "url",
            "name",
        ):
            member = getattr(
                value,
                member_name,
                None,
            )

            if member is None:
                continue

            try:
                member_value = (
                    member()
                    if callable(member)
                    else member
                )
            except Exception:
                continue

            if not member_value:
                continue

            if member_name == "url":
                urls.add(
                    str(member_value)
                )
            else:
                names.add(
                    self.normalized_resource_name(
                        member_value
                    )
                )

        return urls, names

    def source_matches_resources(
        self,
        source: Any,
        candidate_urls: set[str],
        candidate_names: set[str],
    ) -> bool:
        urls, names = (
            self.collect_source_resource_identity(
                source
            )
        )

        if urls.intersection(
            candidate_urls
        ):
            return True

        return bool(
            names.intersection(
                candidate_names
            )
        )

    def iter_texture_set_layer_nodes(
        self,
        texture_set_name: Optional[str],
    ):
        """Yield layers and effects from one Texture Set or from all sets."""
        visited = set()

        def node_key(node):
            try:
                return (
                    "uid",
                    str(node.uid()),
                )
            except Exception:
                return (
                    "object",
                    id(node),
                )

        def walk(node):
            key = node_key(node)

            if key in visited:
                return

            visited.add(key)
            yield node

            for effects_member in (
                "content_effects",
                "mask_effects",
            ):
                getter = getattr(
                    node,
                    effects_member,
                    None,
                )

                if not callable(getter):
                    continue

                try:
                    effects = list(getter())
                except Exception:
                    effects = []

                for effect in effects:
                    yield from walk(effect)

            sub_layers = getattr(
                node,
                "sub_layers",
                None,
            )

            if callable(sub_layers):
                try:
                    children = list(
                        sub_layers()
                    )
                except Exception:
                    children = []

                for child in children:
                    yield from walk(child)

        try:
            texture_sets = list(
                substance_painter.textureset
                .all_texture_sets()
            )
        except Exception:
            return

        for texture_set in texture_sets:
            current_name = (
                self.texture_set_display_name(
                    texture_set
                )
            )

            if (
                texture_set_name
                and current_name
                != texture_set_name
            ):
                continue

            try:
                stacks = list(
                    texture_set.all_stacks()
                )
            except Exception:
                stacks = []

            for stack in stacks:
                try:
                    roots = list(
                        layerstack.get_root_layer_nodes(
                            stack
                        )
                    )
                except Exception:
                    roots = []

                for root in roots:
                    yield from walk(root)

    def source_bindings_for_resources(
        self,
        texture_set_name: Optional[str],
        candidate_urls: set[str],
        candidate_names: set[str],
    ) -> list[tuple[Any, Any]]:
        """Find Fill Layer/Fill Effect inputs that use an old texture."""
        bindings = []
        seen = set()

        for node in self.iter_texture_set_layer_nodes(
            texture_set_name
        ):
            getter = getattr(
                node,
                "get_source",
                None,
            )
            setter = getattr(
                node,
                "set_source",
                None,
            )

            if (
                not callable(getter)
                or not callable(setter)
            ):
                continue

            try:
                active_channels = list(
                    node.active_channels
                )
            except Exception:
                active_channels = []

            for channel in active_channels:
                try:
                    source = getter(channel)
                except Exception:
                    continue

                if not self.source_matches_resources(
                    source,
                    candidate_urls,
                    candidate_names,
                ):
                    continue

                binding_key = (
                    id(node),
                    str(channel),
                )

                if binding_key not in seen:
                    seen.add(binding_key)
                    bindings.append(
                        (
                            node,
                            channel,
                        )
                    )

            # Grayscale Fill Effects and non-split sources use get_source()
            # without a channel argument.
            try:
                source = getter()
            except Exception:
                source = None

            if (
                source is not None
                and self.source_matches_resources(
                    source,
                    candidate_urls,
                    candidate_names,
                )
            ):
                binding_key = (
                    id(node),
                    None,
                )

                if binding_key not in seen:
                    seen.add(binding_key)
                    bindings.append(
                        (
                            node,
                            None,
                        )
                    )

        return bindings

    def project_resource_urls_for_record(
        self,
        record: dict[str, Any],
        candidate_names: set[str],
    ) -> set[str]:
        urls = {
            str(url)
            for url in record.get(
                "painter_resource_urls",
                [],
            )
            if url
        }

        try:
            project_resources = list(
                substance_painter.resource
                .list_project_resources()
            )
        except Exception:
            project_resources = []

        for resource_id in project_resources:
            try:
                resource_name = (
                    self.normalized_resource_name(
                        resource_id.name
                    )
                )
            except Exception:
                continue

            if resource_name not in candidate_names:
                continue

            try:
                urls.add(
                    resource_id.url()
                )
            except Exception:
                pass

        return urls

    def replace_layer_source_bindings(
        self,
        bindings: list[tuple[Any, Any]],
        new_resource_id,
    ) -> int:
        if not bindings:
            return 0

        replaced = 0

        with layerstack.ScopedModification(
            "Relink renamed Bake Manager texture"
        ):
            for node, channel in bindings:
                try:
                    if channel is None:
                        node.set_source(
                            new_resource_id
                        )
                    else:
                        node.set_source(
                            channel,
                            new_resource_id,
                        )

                    replaced += 1

                except Exception:
                    traceback.print_exc()

        return replaced

    def relink_layers_to_renamed_texture(
        self,
        record: dict[str, Any],
        old_path: str,
        new_path: str,
        texture_set_name: Optional[str],
    ) -> int:
        """Import the renamed file and reconnect every layer using the old one."""
        old_stem = os.path.splitext(
            os.path.basename(old_path)
        )[0]
        new_stem = os.path.splitext(
            os.path.basename(new_path)
        )[0]
        candidate_names = {
            self.normalized_resource_name(
                old_stem
            ),
            self.normalized_resource_name(
                new_stem
            ),
        }
        candidate_urls = (
            self.project_resource_urls_for_record(
                record,
                candidate_names,
            )
        )
        bindings = self.source_bindings_for_resources(
            texture_set_name,
            candidate_urls,
            candidate_names,
        )

        if not bindings:
            return 0

        new_resource_id = self.import_texture_resource(
            new_path
        )
        replaced = self.replace_layer_source_bindings(
            bindings,
            new_resource_id,
        )

        if replaced:
            painter_urls = list(
                record.get(
                    "painter_resource_urls",
                    [],
                )
            )
            new_url = new_resource_id.url()

            if new_url not in painter_urls:
                painter_urls.append(
                    new_url
                )

            record[
                "painter_resource_urls"
            ] = painter_urls
            record[
                "last_relinked_resource_url"
            ] = new_url

        return replaced

    @staticmethod
    def layer_node_name(
        node,
    ) -> str:
        try:
            return str(
                node.get_name()
            )
        except Exception:
            pass

        try:
            value = getattr(
                node,
                "name",
                "",
            )

            if callable(value):
                value = value()

            return str(value or "")
        except Exception:
            return ""

    @staticmethod
    def layer_node_uid(
        node,
    ) -> str:
        try:
            return str(
                node.uid()
            )
        except Exception:
            return str(id(node))

    @staticmethod
    def layer_node_children(
        node,
    ) -> list[Any]:
        getter = getattr(
            node,
            "sub_layers",
            None,
        )

        if not callable(getter):
            return []

        try:
            return list(
                getter()
            )
        except Exception:
            return []

    def texture_set_layer_roots(
        self,
        texture_set_name: str,
    ) -> list[Any]:
        roots = []

        try:
            texture_sets = list(
                substance_painter.textureset
                .all_texture_sets()
            )
        except Exception:
            texture_sets = []

        for texture_set in texture_sets:
            if (
                self.texture_set_display_name(
                    texture_set
                )
                != texture_set_name
            ):
                continue

            try:
                stacks = list(
                    texture_set.all_stacks()
                )
            except Exception:
                stacks = []

            for stack in stacks:
                try:
                    roots.extend(
                        layerstack.get_root_layer_nodes(
                            stack
                        )
                    )
                except Exception:
                    continue

        return roots

    def find_named_group(
        self,
        nodes: list[Any],
        accepted_names: set[str],
        recursive: bool = False,
    ):
        accepted = {
            str(name).strip().lower()
            for name in accepted_names
            if str(name).strip()
        }

        for node in nodes:
            if (
                self.node_is_group(node)
                and self.layer_node_name(
                    node
                ).strip().lower()
                in accepted
            ):
                return node

            if recursive:
                found = self.find_named_group(
                    self.layer_node_children(
                        node
                    ),
                    accepted,
                    recursive=True,
                )

                if found is not None:
                    return found

        return None

    def find_named_source_node(
        self,
        parent_group,
        setup_name: str,
    ):
        """Find the Fill Layer/Fill Effect named after a Bake Setup."""
        wanted = str(
            setup_name
        ).strip().lower()

        if not wanted:
            return None

        def walk(nodes):
            for node in nodes:
                if (
                    self.layer_node_name(
                        node
                    ).strip().lower()
                    == wanted
                    and callable(
                        getattr(
                            node,
                            "set_source",
                            None,
                        )
                    )
                ):
                    return node

                found = walk(
                    self.layer_node_children(
                        node
                    )
                )

                if found is not None:
                    return found

            return None

        return walk(
            self.layer_node_children(
                parent_group
            )
        )

    def direct_named_source_node(
        self,
        parent_group,
        accepted_names: set[str],
    ):
        """Find a directly nested Fill Layer/Fill Effect by name."""
        accepted = {
            str(
                name
            ).strip().lower()
            for name in accepted_names
            if str(
                name
            ).strip()
        }

        for node in self.layer_node_children(
            parent_group
        ):
            if (
                self.layer_node_name(
                    node
                ).strip().lower()
                in accepted
                and callable(
                    getattr(
                        node,
                        "set_source",
                        None,
                    )
                )
            ):
                return node

        return None

    @staticmethod
    def bake_setup_hierarchy_tokens(
        setup_name: str,
    ) -> list[str]:
        """Convert a Setup name into optional layer hierarchy tokens.

        Examples:
            Fix_01       -> ["Fix", "01"]
            Fix/Local/01 -> ["Fix", "Local", "01"]

        A layer named exactly like the complete Setup always has priority,
        so existing Setups such as "Fix_01" continue to work unchanged when
        the Layers stack contains a direct layer with that exact name.
        """
        value = str(
            setup_name
        ).strip()

        if not value:
            return []

        value = value.replace(
            "\\",
            "/",
        )

        if "/" in value:
            return [
                part.strip()
                for part in value.split(
                    "/"
                )
                if part.strip()
            ]

        return [
            part.strip()
            for part in value.split(
                "_"
            )
            if part.strip()
        ]

    def find_setup_source_node_by_hierarchy(
        self,
        map_group,
        setup_name: str,
    ) -> tuple[Any, list[str]]:
        """Resolve Setup names to nested groups and a final source layer.

        Resolution order:
        1. Exact full Setup name anywhere below the map group.
        2. Underscore/slash hierarchy, e.g. Fix_01 -> Fix/01.
        3. Longest matching group names first, so Fix_Local_01 may resolve
           either Fix Local/01 or Fix/Local/01 depending on the actual stack.
        """
        exact = self.find_named_source_node(
            map_group,
            setup_name,
        )

        if exact is not None:
            return (
                exact,
                [
                    self.layer_node_name(
                        exact
                    )
                ],
            )

        tokens = (
            self.bake_setup_hierarchy_tokens(
                setup_name
            )
        )

        if len(
            tokens
        ) < 2:
            return (
                None,
                [],
            )

        def resolve(
            parent_group,
            remaining: list[str],
            path: list[str],
        ):
            if not remaining:
                return (
                    None,
                    [],
                )

            # The final one or more tokens may form the target layer name.
            for leaf_count in range(
                len(
                    remaining
                ),
                0,
                -1,
            ):
                leaf_name = "_".join(
                    remaining[
                        -leaf_count:
                    ]
                )
                prefix = remaining[
                    :-leaf_count
                ]

                if not prefix:
                    direct_source = (
                        self.direct_named_source_node(
                            parent_group,
                            {
                                leaf_name,
                            },
                        )
                    )

                    if direct_source is not None:
                        return (
                            direct_source,
                            path
                            + [
                                self.layer_node_name(
                                    direct_source
                                )
                            ],
                        )

            # Try the longest possible group name first. This supports both
            # Fix_Local/01 and Fix/Local/01 without hardcoding either layout.
            for group_token_count in range(
                len(
                    remaining
                )
                - 1,
                0,
                -1,
            ):
                group_name = "_".join(
                    remaining[
                        :group_token_count
                    ]
                )
                group = self.find_named_group(
                    self.layer_node_children(
                        parent_group
                    ),
                    {
                        group_name,
                    },
                    recursive=False,
                )

                if group is None:
                    continue

                found, found_path = resolve(
                    group,
                    remaining[
                        group_token_count:
                    ],
                    path
                    + [
                        self.layer_node_name(
                            group
                        )
                    ],
                )

                if found is not None:
                    return (
                        found,
                        found_path,
                    )

            return (
                None,
                [],
            )

        return resolve(
            map_group,
            tokens,
            [],
        )

    @staticmethod
    def bake_usage_layer_folder_names(
        usage_name: str,
    ) -> set[str]:
        labels = {
            "AO": {
                "AO",
                "Ambient Occlusion",
                "AmbientOcclusion",
            },
            "BentNormals": {
                "BN",
                "Bent Normal",
                "Bent Normals",
                "BentNormals",
            },
            "Curvature": {
                "C",
                "CV",
                "Curvature",
            },
            "Height": {
                "H",
                "Height",
            },
            "ID": {
                "ID",
                "ID Map",
                "IDMap",
            },
            "Normal": {
                "N",
                "Normal",
                "Normal Map",
                "NormalMap",
            },
            "Opacity": {
                "O",
                "Opacity",
            },
            "Position": {
                "P",
                "Position",
            },
            "Thickness": {
                "T",
                "Thickness",
            },
            "WorldSpaceNormal": {
                "WSN",
                "World Space Normal",
                "WorldSpaceNormal",
            },
        }

        result = set(
            labels.get(
                usage_name,
                set(),
            )
        )
        result.add(
            BAKE_USAGE_LABELS.get(
                usage_name,
                usage_name,
            )
        )
        result.add(
            usage_name
        )
        return result

    def set_node_bitmap_source(
        self,
        node,
        resource_id,
        usage_name: str = "",
    ) -> int:
        """Assign a bitmap only to the intended material channel.

        Normal bake maps must never be copied into Base Color, Roughness,
        Height, or any other active channel on the same Fill Layer.
        """
        setter = getattr(
            node,
            "set_source",
            None,
        )

        if not callable(setter):
            return 0

        active_channels = getattr(
            node,
            "active_channels",
            [],
        )

        if callable(active_channels):
            try:
                active_channels = (
                    active_channels()
                )
            except Exception:
                active_channels = []

        try:
            active_channels = list(
                active_channels
            )
        except Exception:
            active_channels = []

        usage_name = str(
            usage_name
        ).strip()

        if usage_name == "Normal":
            normal_channel = None

            for channel in active_channels:
                channel_name = getattr(
                    channel,
                    "name",
                    str(channel),
                )

                if callable(channel_name):
                    try:
                        channel_name = channel_name()
                    except Exception:
                        channel_name = str(channel)

                normalized_name = (
                    self.normalize_enum_key(
                        channel_name
                    )
                )

                if (
                    normalized_name == "normal"
                    or normalized_name.endswith(
                        "normal"
                    )
                ):
                    normal_channel = channel
                    break

            # Fallback to the enum member itself when active_channels is
            # unavailable but Painter still allows direct assignment.
            if normal_channel is None:
                normal_channel = getattr(
                    layerstack.ChannelType,
                    "Normal",
                    None,
                )

            if normal_channel is None:
                return 0

            try:
                setter(
                    normal_channel,
                    resource_id,
                )
                return 1
            except Exception:
                traceback.print_exc()
                return 0

        assigned = 0

        if active_channels:
            for channel in active_channels:
                try:
                    setter(
                        channel,
                        resource_id,
                    )
                    assigned += 1
                except Exception:
                    traceback.print_exc()

            return assigned

        # Grayscale Fill Effects and other unsplit source nodes.
        try:
            setter(
                resource_id
            )
            return 1
        except Exception:
            traceback.print_exc()
            return 0

    @staticmethod
    def node_active_channels(
        node,
    ) -> list[Any]:
        channels = getattr(
            node,
            "active_channels",
            [],
        )

        if callable(
            channels
        ):
            try:
                channels = channels()
            except Exception:
                channels = []

        try:
            return list(
                channels
            )
        except Exception:
            return []

    def bake_record_resource_identity(
        self,
        record: dict[str, Any],
        source_url: Optional[str] = None,
    ) -> tuple[set[str], set[str]]:
        urls = {
            str(
                value
            )
            for value in record.get(
                "painter_resource_urls",
                [],
            )
            if str(
                value
            )
        }

        if (
            source_url
            and str(
                source_url
            ).startswith(
                "resource://"
            )
        ):
            urls.add(
                str(
                    source_url
                )
            )

        names = set()

        for value in (
            record.get(
                "original_name",
                "",
            ),
            record.get(
                "alias",
                "",
            ),
            os.path.splitext(
                os.path.basename(
                    str(
                        record.get(
                            "preview_path",
                            "",
                        )
                    )
                )
            )[0],
        ):
            normalized = (
                self.normalized_resource_name(
                    value
                )
            )

            if normalized:
                names.add(
                    normalized
                )

        return (
            urls,
            names,
        )

    def target_node_uses_bake_record(
        self,
        target_node,
        record: dict[str, Any],
        usage_name: str,
        source_url: Optional[str] = None,
    ) -> bool:
        """Check the actual layer source before assigning it again."""
        getter = getattr(
            target_node,
            "get_source",
            None,
        )

        if not callable(
            getter
        ):
            return False

        candidate_urls, candidate_names = (
            self.bake_record_resource_identity(
                record,
                source_url=source_url,
            )
        )

        sources = []

        # Fill Effects expose get_source() without a channel.
        try:
            sources.append(
                getter()
            )
        except Exception:
            pass

        channels = (
            self.node_active_channels(
                target_node
            )
        )

        if str(
            usage_name
        ).strip() == "Normal":
            channels = [
                channel
                for channel in channels
                if (
                    self.normalize_enum_key(
                        getattr(
                            channel,
                            "name",
                            str(
                                channel
                            ),
                        )()
                        if callable(
                            getattr(
                                channel,
                                "name",
                                None,
                            )
                        )
                        else getattr(
                            channel,
                            "name",
                            str(
                                channel
                            ),
                        )
                    )
                    .endswith(
                        "normal"
                    )
                )
            ]

            if not channels:
                normal_channel = getattr(
                    layerstack.ChannelType,
                    "Normal",
                    None,
                )

                if normal_channel is not None:
                    channels = [
                        normal_channel
                    ]

        for channel in channels:
            try:
                sources.append(
                    getter(
                        channel
                    )
                )
            except Exception:
                continue

        return any(
            self.source_matches_resources(
                source,
                candidate_urls,
                candidate_names,
            )
            for source in sources
            if source is not None
        )

    def auto_assign_bake_record_to_smart_material(
        self,
        record: dict[str, Any],
        source_url: Optional[str] = None,
        root_group=None,
    ) -> int:
        """Route TextureSet_Map_Setup into Set/Map/Setup layer hierarchy."""
        texture_set_name = str(
            record.get(
                "texture_set_name",
                "",
            )
        ).strip()
        usage_name = str(
            record.get(
                "bake_usage",
                "",
            )
        ).strip()
        setup_name = str(
            record.get(
                "bake_setup",
                "",
            )
        ).strip()
        file_path = record.get(
            "preview_path",
            "",
        )

        if (
            not texture_set_name
            or not usage_name
            or not setup_name
            or not file_path
            or not os.path.isfile(
                str(file_path)
            )
        ):
            return 0

        if root_group is None:
            root_group = self.find_named_group(
                self.texture_set_layer_roots(
                    texture_set_name
                ),
                {
                    texture_set_name,
                },
                recursive=False,
            )

        if root_group is None:
            return 0

        map_group = self.find_named_group(
            self.layer_node_children(
                root_group
            ),
            self.bake_usage_layer_folder_names(
                usage_name
            ),
            recursive=False,
        )

        if map_group is None:
            return 0

        target_node, target_relative_path = (
            self.find_setup_source_node_by_hierarchy(
                map_group,
                setup_name,
            )
        )

        if target_node is None:
            print(
                "[BakeManager] Auto-assign target not found: "
                f'{texture_set_name}/'
                f'{BAKE_USAGE_LABELS.get(usage_name, usage_name)}/'
                f'{setup_name}.'
            )
            return 0

        assigned_path = "/".join(
            [
                texture_set_name,
                BAKE_USAGE_LABELS.get(
                    usage_name,
                    usage_name,
                ),
            ]
            + (
                target_relative_path
                or [
                    setup_name
                ]
            )
        )

        if self.target_node_uses_bake_record(
            target_node,
            record,
            usage_name,
            source_url=source_url,
        ):
            record[
                "auto_assigned_layer_path"
            ] = assigned_path
            return 0

        try:
            resource_id, _was_imported = (
                self.resolve_assignment_resource(
                    os.path.normpath(
                        str(file_path)
                    ),
                    source_url=source_url,
                    preferred_urls=record.get(
                        "painter_resource_urls",
                        [],
                    ),
                )
            )
        except Exception:
            traceback.print_exc()
            return 0

        with layerstack.ScopedModification(
            "Auto-assign Bake Manager texture"
        ):
            assigned = self.set_node_bitmap_source(
                target_node,
                resource_id,
                usage_name=usage_name,
            )

        if assigned:
            painter_urls = list(
                record.get(
                    "painter_resource_urls",
                    [],
                )
            )
            painter_url = resource_id.url()

            if painter_url not in painter_urls:
                painter_urls.append(
                    painter_url
                )

            record[
                "painter_resource_urls"
            ] = painter_urls
            record[
                "auto_assigned_layer_path"
            ] = assigned_path

        return assigned

    def auto_assign_all_bake_records_for_texture_set(
        self,
        texture_set_name: str,
        root_group=None,
    ) -> int:
        assigned = 0

        for resource_url, record in (
            self._data.get(
                "resources",
                {},
            ).items()
        ):
            if (
                record.get("source")
                != "Bake Manager Setup"
                or str(
                    record.get(
                        "texture_set_name",
                        "",
                    )
                )
                != texture_set_name
            ):
                continue

            assigned += (
                self.auto_assign_bake_record_to_smart_material(
                    record,
                    source_url=resource_url,
                    root_group=root_group,
                )
            )

        if assigned:
            self.save_data()

        return assigned

    def refresh_bake_layer_assignments(
        self,
    ) -> tuple[int, int]:
        """Check all saved Setup maps and repair missing layer assignments."""
        checked = 0
        assigned = 0

        for resource_url, record in list(
            self._data.get(
                "resources",
                {},
            ).items()
        ):
            if (
                record.get(
                    "source"
                )
                != "Bake Manager Setup"
            ):
                continue

            file_path = record.get(
                "preview_path",
                "",
            )

            if (
                not file_path
                or not os.path.isfile(
                    str(
                        file_path
                    )
                )
            ):
                continue

            checked += 1
            assigned += (
                self.auto_assign_bake_record_to_smart_material(
                    record,
                    source_url=resource_url,
                )
            )

        if checked:
            self.save_data()

        return (
            checked,
            assigned,
        )

    def export_bake_setup_variants(
        self,
        entry: dict[str, Any],
    ) -> int:
        cache_dir = self.preview_cache_dir()

        if not cache_dir:
            return 0

        os.makedirs(cache_dir, exist_ok=True)
        set_name = entry["set"]
        setup_name = entry["setup"]
        active_bakers = entry["active_bakers"]
        targets = {
            f"setup|{set_name}|{usage}": (set_name, usage)
            for usage in active_bakers
        }
        exported = self.export_mesh_map_previews(
            substance_painter.export,
            cache_dir,
            targets,
        )
        resources = self._data.setdefault("resources", {})
        folder = self.texture_set_folder_path(set_name)
        made = 0

        for usage in active_bakers:
            key = f"setup|{set_name}|{usage}"
            source_path = exported.get((key, usage))

            if not source_path or not os.path.isfile(source_path):
                continue

            suffix = MESH_MAP_FILE_SUFFIXES.get(usage, usage)
            # Stable routing name:
            # <Texture Set>_<Map>_<Setup>, e.g. Cab_AO_Base.
            stem = "_".join(
                (
                    self.safe_bake_name(set_name),
                    self.safe_bake_name(suffix),
                    self.safe_bake_name(setup_name),
                )
            )
            destination_directory = (
                self.texture_set_disk_directory(
                    set_name
                )
            )

            if not destination_directory:
                continue

            os.makedirs(
                destination_directory,
                exist_ok=True,
            )
            destination_path = os.path.join(
                destination_directory,
                stem + ".png",
            )

            if os.path.normcase(source_path) != os.path.normcase(
                destination_path
            ):
                shutil.copy2(source_path, destination_path)

            url = self.bake_setup_resource_url(destination_path)

            for old_url, record in list(resources.items()):
                if (
                    old_url != url
                    and record.get("source") == "Bake Manager Setup"
                    and os.path.normcase(
                        os.path.abspath(
                            str(record.get("preview_path", ""))
                        )
                    )
                    == os.path.normcase(os.path.abspath(destination_path))
                ):
                    resources.pop(old_url, None)

            existing_record = resources.get(
                url,
                {}
            )
            record = {
                "original_name": stem,
                "alias": stem,
                "folder": folder,
                "type": BAKE_USAGE_TYPES.get(usage, "Texture"),
                "source": "Bake Manager Setup",
                "available": True,
                "painter_active": False,
                "preview_path": os.path.normpath(destination_path),
                "exported_file_name": os.path.basename(destination_path),
                "texture_set_name": set_name,
                "bake_setup": setup_name,
                "bake_usage": usage,
                "painter_resource_urls": list(
                    existing_record.get(
                        "painter_resource_urls",
                        [],
                    )
                ),
            }
            resources[url] = record

            relinked = (
                self.relink_layers_to_renamed_texture(
                    record,
                    source_path,
                    destination_path,
                    set_name,
                )
            )
            record[
                "relinked_layer_sources"
            ] = relinked

            auto_assigned = (
                self.auto_assign_bake_record_to_smart_material(
                    record,
                    source_url=url,
                )
            )
            record[
                "auto_assigned_layer_sources"
            ] = auto_assigned
            made += 1

        if made:
            self._preview_cache.clear()
            self.save_data()
            self.populate_asset_tiles()

        return made

    def finish_bake_setup_queue(self):
        self._bake_setup_running = False
        self._bake_setup_queue_index = -1
        self.bake_setups_button.setEnabled(True)
        self.clear_mesh_maps_button.setEnabled(True)
        self.bake_setup_progress.setValue(0)

        try:
            substance_painter.ui.switch_to_mode(
                substance_painter.ui.UIMode.Edition
            )
        except Exception:
            pass

        done = sum(
            1
            for entry in self._bake_setup_queue
            if entry.get("status") == "done"
        )

        # Prevent the normal auto-export watcher from treating the queue's
        # last bake as a separate manual bake and creating another copy.
        self._last_mesh_map_signature = self.collect_mesh_map_signature()
        self._painter_was_busy = False

        self.status_label.setText(
            f"Bake finished: {done}/{len(self._bake_setup_queue)} Setup pass(es)."
        )

    @staticmethod
    def texture_set_display_name(
        texture_set,
    ) -> str:
        try:
            name = texture_set.name()

            if name:
                return str(name)
        except Exception:
            pass

        return str(texture_set)

    def clear_texture_set_mesh_map_slot(
        self,
        texture_set,
        usage,
    ):
        """Clear one Mesh Map slot across Painter API revisions."""
        for method_name in (
            "clear_mesh_map_resource",
            "remove_mesh_map_resource",
        ):
            method = getattr(
                texture_set,
                method_name,
                None,
            )

            if not callable(method):
                continue

            method(usage)
            return

        setter = getattr(
            texture_set,
            "set_mesh_map_resource",
            None,
        )

        if not callable(setter):
            raise RuntimeError(
                "This Painter build exposes no Mesh Map clearing method."
            )

        # Painter 11.x clears a slot when None is assigned.
        setter(
            usage,
            None,
        )

    def clear_all_mesh_maps(self):
        if not substance_painter.project.is_open():
            self.status_label.setText(
                "Open a Painter project first."
            )
            return

        try:
            texture_sets = list(
                substance_painter.textureset.all_texture_sets()
            )
            usage_items = list(
                substance_painter.textureset
                .MeshMapUsage.__members__.items()
            )
        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not read the Texture Set Mesh Map slots."
            )
            return

        assigned_slots = []

        for texture_set in texture_sets:
            texture_set_name = (
                self.texture_set_display_name(
                    texture_set
                )
            )

            for usage_name, usage in usage_items:
                try:
                    resource_id = (
                        texture_set.get_mesh_map_resource(
                            usage
                        )
                    )
                except Exception:
                    continue

                if resource_id is None:
                    continue

                assigned_slots.append(
                    (
                        texture_set,
                        texture_set_name,
                        usage_name,
                        usage,
                    )
                )

        if not assigned_slots:
            self.status_label.setText(
                "No assigned Mesh Maps to clear."
            )
            return

        affected_sets = {
            texture_set_name
            for (
                _texture_set,
                texture_set_name,
                _usage_name,
                _usage,
            ) in assigned_slots
        }

        answer = QtWidgets.QMessageBox.question(
            self,
            "Clear Mesh Maps",
            (
                f"Clear {len(assigned_slots)} Mesh Map slot(s) "
                f"across {len(affected_sets)} Texture Set(s)?\n\n"
                "Exported PNG files and Bake Manager tiles "
                "will not be deleted."
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )

        if (
            answer
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return

        cleared = 0
        failed = []

        for (
            texture_set,
            texture_set_name,
            usage_name,
            usage,
        ) in assigned_slots:
            try:
                self.clear_texture_set_mesh_map_slot(
                    texture_set,
                    usage,
                )
                cleared += 1

            except Exception as error:
                traceback.print_exc()
                failed.append(
                    (
                        texture_set_name,
                        usage_name,
                        str(error),
                    )
                )

        self._last_mesh_map_signature = (
            self.collect_mesh_map_signature()
        )
        self._painter_was_busy = False

        try:
            self.synchronize_project_resources()
            self.populate_asset_tiles()
            self.save_data()
        except Exception:
            traceback.print_exc()

        if failed:
            failed_text = "\n".join(
                f"• {set_name}: {usage_name}"
                for (
                    set_name,
                    usage_name,
                    _error,
                ) in failed[:12]
            )

            if len(failed) > 12:
                failed_text += (
                    f"\n• …and "
                    f"{len(failed) - 12} more"
                )

            QtWidgets.QMessageBox.warning(
                self,
                "Some Mesh Maps Were Not Cleared",
                (
                    f"Cleared {cleared} slot(s), but "
                    f"{len(failed)} failed:\n\n"
                    + failed_text
                    + "\n\nDetails are in the Python Console."
                ),
            )

        self.status_label.setText(
            f"Cleared {cleared} Mesh Map slot(s)"
            + (
                f"; {len(failed)} failed."
                if failed
                else "."
            )
        )

    # ------------------------------------------------------------------
    # Quick Smart Materials
    # ------------------------------------------------------------------

    @staticmethod
    def node_is_group(node) -> bool:
        try:
            return (
                node.get_type()
                == layerstack.NodeType.GroupLayer
            )
        except Exception:
            return False

    def private_smart_material_directory(
        self,
    ) -> str:
        """Private Smart Materials live directly in the plugin root."""
        return self.plugin_root_directory()

    def legacy_private_smart_material_directory(
        self,
    ) -> str:
        return os.path.join(
            self.plugin_root_directory(),
            "BakeSmartMat",
        )

    @staticmethod
    def safe_smart_material_file_name(
        value: str,
    ) -> str:
        safe_name = str(
            value
        ).strip()

        for invalid_character in '<>:"/\\|?*':
            safe_name = safe_name.replace(
                invalid_character,
                "_",
            )

        safe_name = safe_name.rstrip(
            ". "
        )

        return safe_name or "Smart Mat"

    def smart_material_name_is_file_safe(
        self,
        material_name: str,
    ) -> bool:
        material_name = str(
            material_name
        )

        return (
            bool(
                material_name.strip()
            )
            and material_name
            == material_name.strip()
            and material_name
            == self.safe_smart_material_file_name(
                material_name
            )
        )

    def private_smart_material_file_name(
        self,
        project_name: str,
        material_name: str,
    ) -> str:
        # Smart Materials are global, not tied to a Bake Project. Keeping the
        # exact user name makes the button, file and portable material match.
        del project_name
        return (
            str(
                material_name
            )
            + ".spsm"
        )

    def private_smart_material_file_path(
        self,
        project_name: str,
        material_name: str,
    ) -> str:
        return os.path.join(
            self.private_smart_material_directory(),
            self.private_smart_material_file_name(
                project_name,
                material_name,
            ),
        )

    def decode_private_smart_material_file(
        self,
        file_name: str,
    ) -> tuple[str, str]:
        """Decode current and older Bake Manager SPSM file names."""
        stem = os.path.splitext(
            os.path.basename(
                file_name
            )
        )[0]
        material_name = stem

        if stem.startswith(
            "BakeSmartMat__"
        ):
            legacy_payload = stem[len(
                "BakeSmartMat__"
            ):]
            parts = legacy_payload.split(
                "__",
                1,
            )
            material_name = (
                parts[-1]
                if parts
                else legacy_payload
            )

        elif stem.startswith(
            "BakeSmartMat_"
        ):
            legacy_payload = stem[len(
                "BakeSmartMat_"
            ):]

            if "__" in legacy_payload:
                material_name = legacy_payload.split(
                    "__",
                    1,
                )[-1]
            else:
                material_name = legacy_payload

        return (
            "",
            material_name.strip()
            or "Smart Mat",
        )

    def ensure_private_smart_material_ignore_rule(
        self,
    ):
        """Prevent plugin-root SPSM files from appearing in Painter Assets."""
        ignore_path = os.path.join(
            self.private_smart_material_directory(),
            ".ignore_assets_pt",
        )
        marker = (
            "# Bake Manager private Smart Materials"
        )
        rule = "*.spsm"

        try:
            existing = ""

            if os.path.isfile(
                ignore_path
            ):
                existing = Path(
                    ignore_path
                ).read_text(
                    encoding="utf-8",
                    errors="ignore",
                )

            existing_lines = {
                line.strip()
                for line in existing.splitlines()
            }
            additions = []

            if marker not in existing_lines:
                additions.append(
                    marker
                )

            if rule not in existing_lines:
                additions.append(
                    rule
                )

            if additions:
                prefix = (
                    existing.rstrip()
                    + "\n\n"
                    if existing.strip()
                    else ""
                )
                Path(
                    ignore_path
                ).write_text(
                    prefix
                    + "\n".join(
                        additions
                    )
                    + "\n",
                    encoding="utf-8",
                )

        except OSError:
            traceback.print_exc()

    def legacy_smart_material_name_map(
        self,
    ) -> dict[str, str]:
        result = {}

        for project_data in (
            self.bake_manager_data()
            .setdefault(
                "projects",
                {},
            )
            .values()
        ):
            materials = project_data.get(
                "smart_materials",
                {},
            )

            if not isinstance(
                materials,
                dict,
            ):
                continue

            for material_name, metadata in materials.items():
                if not isinstance(
                    metadata,
                    dict,
                ):
                    continue

                file_name = os.path.basename(
                    str(
                        metadata.get(
                            "spsm_file",
                            "",
                        )
                    )
                )

                if file_name:
                    result[
                        file_name.lower()
                    ] = str(
                        material_name
                    )

        return result

    def migrate_one_private_smart_material(
        self,
        source_path: str,
        material_name: str,
    ) -> Optional[str]:
        material_name = str(
            material_name
        ).strip()

        if not material_name:
            return None

        safe_name = (
            self.safe_smart_material_file_name(
                material_name
            )
        )
        destination = os.path.join(
            self.private_smart_material_directory(),
            safe_name + ".spsm",
        )

        try:
            if (
                os.path.normcase(
                    os.path.abspath(
                        source_path
                    )
                )
                == os.path.normcase(
                    os.path.abspath(
                        destination
                    )
                )
            ):
                return destination

            if os.path.isfile(
                destination
            ):
                # Keep the newest valid file and discard the old prefixed copy.
                source_mtime = os.path.getmtime(
                    source_path
                )
                destination_mtime = os.path.getmtime(
                    destination
                )

                if source_mtime > destination_mtime:
                    os.replace(
                        source_path,
                        destination,
                    )
                else:
                    os.remove(
                        source_path
                    )
            else:
                try:
                    os.replace(
                        source_path,
                        destination,
                    )
                except OSError:
                    shutil.copy2(
                        source_path,
                        destination,
                    )
                    os.remove(
                        source_path
                    )

            return destination

        except OSError:
            traceback.print_exc()
            return None

    def migrate_legacy_private_smart_materials(
        self,
    ):
        """Move old project-prefixed SPSM files to <User Name>.spsm."""
        root = self.private_smart_material_directory()
        legacy_name_map = (
            self.legacy_smart_material_name_map()
        )
        legacy_directory = (
            self.legacy_private_smart_material_directory()
        )

        source_paths = []

        if os.path.isdir(
            legacy_directory
        ):
            source_paths.extend(
                os.path.join(
                    legacy_directory,
                    file_name,
                )
                for file_name in os.listdir(
                    legacy_directory
                )
                if file_name.lower().endswith(
                    ".spsm"
                )
            )

        try:
            source_paths.extend(
                os.path.join(
                    root,
                    file_name,
                )
                for file_name in os.listdir(
                    root
                )
                if (
                    file_name.lower().endswith(
                        ".spsm"
                    )
                    and (
                        file_name.startswith(
                            "BakeSmartMat__"
                        )
                        or file_name.startswith(
                            "BakeSmartMat_"
                        )
                    )
                )
            )
        except OSError:
            pass

        for source_path in source_paths:
            file_name = os.path.basename(
                source_path
            )
            material_name = legacy_name_map.get(
                file_name.lower()
            )

            if not material_name:
                _project_name, material_name = (
                    self.decode_private_smart_material_file(
                        file_name
                    )
                )

            self.migrate_one_private_smart_material(
                source_path,
                material_name,
            )

        try:
            if (
                os.path.isdir(
                    legacy_directory
                )
                and not os.listdir(
                    legacy_directory
                )
            ):
                os.rmdir(
                    legacy_directory
                )
        except OSError:
            pass

    def private_smart_material_catalog(
        self,
    ) -> dict[str, dict[str, Any]]:
        self.ensure_private_smart_material_ignore_rule()
        self.migrate_legacy_private_smart_materials()
        catalog = {}
        root = self.private_smart_material_directory()

        try:
            file_names = sorted(
                os.listdir(
                    root
                ),
                key=str.lower,
            )
        except OSError:
            file_names = []

        for file_name in file_names:
            if (
                not file_name.lower().endswith(
                    ".spsm"
                )
                or file_name.startswith(
                    "BakeManager_Temp_"
                )
            ):
                continue

            _project_name, material_name = (
                self.decode_private_smart_material_file(
                    file_name
                )
            )
            material_name = str(
                material_name
            ).strip()

            if not material_name:
                continue

            catalog[
                material_name
            ] = {
                "name": material_name,
                "spsm_file": file_name,
                "format": (
                    "Bake Manager private Smart Material"
                ),
                "version": 4,
            }

        return catalog

    def scan_private_smart_materials(
        self,
    ) -> int:
        """Load every plugin-root SPSM into one global Smart Mat catalog."""
        catalog = (
            self.private_smart_material_catalog()
        )
        projects = (
            self.bake_manager_data()
            .setdefault(
                "projects",
                {},
            )
        )

        if not projects:
            projects[
                "Project"
            ] = {
                "setups": {},
                "smart_materials": {},
                "checked_setups": [],
            }

        for project_data in projects.values():
            project_data[
                "smart_materials"
            ] = {
                name: dict(
                    metadata
                )
                for name, metadata in catalog.items()
            }

        self._global_smart_material_catalog = catalog

        if not self._private_smart_material_cleanup_scheduled:
            self._private_smart_material_cleanup_scheduled = True
            QtCore.QTimer.singleShot(
                1200,
                self.cleanup_private_smart_material_asset_duplicates,
            )

        return len(
            catalog
        )

    def get_private_smart_material_metadata(
        self,
        material_name: str,
    ) -> Optional[dict[str, Any]]:
        catalog = (
            self.private_smart_material_catalog()
        )
        metadata = catalog.get(
            str(
                material_name
            )
        )

        return (
            dict(
                metadata
            )
            if isinstance(
                metadata,
                dict,
            )
            else None
        )

    def apply_shared_bake_smart_mat(
        self,
        create_if_missing: bool = True,
        path: Optional[str] = None,
    ) -> bool:
        del create_if_missing, path
        return bool(
            self.scan_private_smart_materials()
        )

    def user_shelf_path(
        self,
    ) -> Optional[str]:
        """Return the user shelf path without using deprecated API calls."""
        try:
            shelf = (
                substance_painter.resource
                .Shelves.user_shelf()
            )
            shelf_path = getattr(
                shelf,
                "path",
                None,
            )

            # Painter 11 exposes path as a property. Older builds exposed
            # the same value through a method.
            if callable(
                shelf_path
            ):
                shelf_path = shelf_path()

            if not shelf_path:
                return None

            return os.path.normpath(
                str(shelf_path)
            )

        except Exception:
            return None

    def ensure_temporary_smart_material_ignore_rule(
        self,
    ):
        """Hide Bake Manager temporary SPSM files from Painter Assets."""
        shelf_path = self.user_shelf_path()

        if (
            not shelf_path
            or not os.path.isdir(
                shelf_path
            )
        ):
            return

        smart_materials_directory = os.path.join(
            shelf_path,
            "smart-materials",
        )

        try:
            os.makedirs(
                smart_materials_directory,
                exist_ok=True,
            )
        except OSError:
            traceback.print_exc()
            return

        ignore_path = os.path.join(
            smart_materials_directory,
            ".ignore_assets_pt",
        )
        marker = (
            "# Bake Manager temporary Smart Materials"
        )
        rule = "BakeManager_Temp_*"

        try:
            existing = ""

            if os.path.isfile(
                ignore_path
            ):
                existing = Path(
                    ignore_path
                ).read_text(
                    encoding="utf-8",
                    errors="ignore",
                )

            existing_lines = {
                line.strip()
                for line in existing.splitlines()
            }

            additions = []

            if marker not in existing_lines:
                additions.append(marker)

            if rule not in existing_lines:
                additions.append(rule)

            if not additions:
                return

            prefix = (
                existing.rstrip()
                + "\n\n"
                if existing.strip()
                else ""
            )
            Path(
                ignore_path
            ).write_text(
                prefix
                + "\n".join(additions)
                + "\n",
                encoding="utf-8",
            )

        except OSError:
            traceback.print_exc()

    def purge_bake_manager_temporary_spsm_files(
        self,
    ):
        """Quietly remove stale temporary SPSM files that are not locked."""
        shelf_path = self.user_shelf_path()

        if (
            not shelf_path
            or not os.path.isdir(
                shelf_path
            )
        ):
            return

        for root, _directories, file_names in os.walk(
            shelf_path
        ):
            for file_name in file_names:
                if (
                    not file_name.lower().endswith(
                        ".spsm"
                    )
                    or not file_name.startswith(
                        "BakeManager_Temp_"
                    )
                ):
                    continue

                temporary_path = os.path.join(
                    root,
                    file_name,
                )

                try:
                    os.remove(
                        temporary_path
                    )
                except PermissionError:
                    # Painter still owns this resource. It will be retried
                    # after the native Assets deletion releases the file.
                    continue
                except OSError:
                    continue

    def refresh_painter_resource_libraries(
        self,
    ):
        """Best-effort refresh after removing a temporary shelf resource."""
        try:
            shelf = (
                substance_painter.resource
                .Shelves.user_shelf()
            )

            for method_name in (
                "refresh",
                "reload",
                "rescan",
                "update",
            ):
                method = getattr(
                    shelf,
                    method_name,
                    None,
                )

                if callable(method):
                    try:
                        method()
                        break
                    except Exception:
                        continue

        except Exception:
            pass

        # Painter builds expose different internal JS refresh names.
        # Probe them safely instead of assuming one fixed API.
        try:
            spjs.evaluate(
                """
                (function () {
                    var resources = alg.resources || {};
                    var names = [
                        "refresh",
                        "reload",
                        "reloadResources",
                        "refreshResources",
                        "rescan",
                        "update"
                    ];

                    for (var i = 0; i < names.length; ++i) {
                        var fn = resources[names[i]];

                        if (typeof fn !== "function") {
                            continue;
                        }

                        try {
                            fn.call(resources);
                            return names[i];
                        } catch (error) {
                        }
                    }

                    return "";
                })()
                """
            )
        except Exception:
            pass

    def locate_created_smart_material_file(
        self,
        material_name: str,
        created_after: float = 0.0,
    ) -> Optional[str]:
        try:
            shelf_path = (
                substance_painter.resource
                .Shelves.user_shelf()
                .path()
            )
        except Exception:
            shelf_path = None

        if (
            not shelf_path
            or not os.path.isdir(
                shelf_path
            )
        ):
            return None

        normalized_target = (
            self.safe_smart_material_file_name(
                material_name
            ).lower()
        )
        best_path = None
        best_modified = -1.0

        for root, _directories, file_names in os.walk(
            shelf_path
        ):
            for file_name in file_names:
                if not file_name.lower().endswith(
                    ".spsm"
                ):
                    continue

                file_stem = os.path.splitext(
                    file_name
                )[0]

                if (
                    self.safe_smart_material_file_name(
                        file_stem
                    ).lower()
                    != normalized_target
                ):
                    continue

                candidate = os.path.join(
                    root,
                    file_name,
                )

                try:
                    modified = os.path.getmtime(
                        candidate
                    )
                except OSError:
                    modified = 0.0

                if (
                    modified + 2.0 < created_after
                    or modified <= best_modified
                ):
                    continue

                best_modified = modified
                best_path = candidate

        return best_path

    def resource_id_from_import_result(
        self,
        result,
    ):
        if result is None:
            return None

        if isinstance(
            result,
            substance_painter.resource.ResourceID,
        ):
            return result

        identifier = getattr(
            result,
            "identifier",
            None,
        )

        if callable(identifier):
            try:
                resource_id = identifier()

                if isinstance(
                    resource_id,
                    substance_painter.resource.ResourceID,
                ):
                    return resource_id
            except Exception:
                pass

        if isinstance(
            result,
            (
                list,
                tuple,
            ),
        ):
            for item in result:
                resource_id = (
                    self.resource_id_from_import_result(
                        item
                    )
                )

                if resource_id is not None:
                    return resource_id

        return None

    def import_private_smart_material_resource(
        self,
        file_path: str,
    ):
        """Import into the current project, never the global shelf."""
        importer = (
            substance_painter.resource
            .import_project_resource
        )
        usage = getattr(
            substance_painter.resource.Usage,
            "SMART_MATERIAL",
            None,
        )

        if usage is None:
            for name in dir(
                substance_painter.resource.Usage
            ):
                if (
                    self.normalize_enum_key(
                        name
                    )
                    == "smartmaterial"
                ):
                    usage = getattr(
                        substance_painter.resource.Usage,
                        name,
                    )
                    break

        attempts = []

        if usage is not None:
            attempts.extend(
                (
                    (
                        file_path,
                        usage,
                    ),
                    (
                        file_path,
                        usage,
                        None,
                    ),
                )
            )

        errors = []

        for arguments in attempts:
            try:
                result = importer(
                    *arguments
                )
                resource_id = (
                    self.resource_id_from_import_result(
                        result
                    )
                )

                if resource_id is not None:
                    return resource_id

                errors.append(
                    "Import returned no ResourceID."
                )

            except Exception as error:
                errors.append(
                    str(error)
                )

        raise RuntimeError(
            "Painter could not import the private Smart Material "
            "into the current project:\n"
            + "\n".join(errors)
        )

    def quietly_delete_painter_resource(
        self,
        resource_url: str,
        final_status: str = "",
    ):
        resource_objects = (
            self.resource_objects_from_urls(
                [
                    resource_url
                ]
            )
        )

        if not resource_objects:
            if final_status:
                self.status_label.setText(
                    final_status
                )
            return

        try:
            substance_painter.resource.show_resources_in_ui(
                resource_objects
            )
        except Exception:
            traceback.print_exc()

            if final_status:
                self.status_label.setText(
                    final_status
                    + " Temporary Assets cleanup failed."
                )

            return

        QtCore.QTimer.singleShot(
            350,
            self.send_delete_key_to_assets,
        )

        if final_status:
            QtCore.QTimer.singleShot(
                1000,
                lambda text=final_status: (
                    self.status_label.setText(
                        text
                    )
                ),
            )

    def remove_original_shelf_spsm(
        self,
        source_path: str,
        private_path: str,
    ):
        if (
            not source_path
            or not os.path.isfile(
                source_path
            )
        ):
            return

        if (
            os.path.normcase(
                os.path.abspath(
                    source_path
                )
            )
            == os.path.normcase(
                os.path.abspath(
                    private_path
                )
            )
        ):
            return

        try:
            os.remove(
                source_path
            )
        except OSError:
            traceback.print_exc()

    def retry_remove_temporary_spsm(
        self,
        source_path: str,
        temporary_resource_url: str,
        final_status: str,
        attempt: int = 0,
    ):
        """Remove a temporary shelf file after Painter releases its handle."""
        if not source_path:
            self.status_label.setText(
                final_status
            )
            return

        if not os.path.isfile(
            source_path
        ):
            self.refresh_painter_resource_libraries()
            self.status_label.setText(
                final_status
            )
            return

        try:
            os.remove(
                source_path
            )

        except PermissionError:
            # Painter may keep the SPSM open for several seconds after the
            # resource was deleted from Assets.
            if attempt in (
                2,
                6,
                12,
            ):
                self.quietly_delete_painter_resource(
                    temporary_resource_url
                )
                self.refresh_painter_resource_libraries()

            if attempt < 24:
                delay = min(
                    250 + attempt * 125,
                    1500,
                )
                QtCore.QTimer.singleShot(
                    delay,
                    lambda: (
                        self.retry_remove_temporary_spsm(
                            source_path,
                            temporary_resource_url,
                            final_status,
                            attempt + 1,
                        )
                    ),
                )
                return

            self.status_label.setText(
                final_status
                + " Painter is still locking the temporary file; "
                "it will be removed on the next plugin refresh or restart."
            )
            return

        except OSError:
            if attempt < 8:
                QtCore.QTimer.singleShot(
                    500,
                    lambda: (
                        self.retry_remove_temporary_spsm(
                            source_path,
                            temporary_resource_url,
                            final_status,
                            attempt + 1,
                        )
                    ),
                )
                return

            self.status_label.setText(
                final_status
                + " The temporary shelf file could not be removed."
            )
            return

        self.refresh_painter_resource_libraries()
        self.status_label.setText(
            final_status
        )

    def delete_stale_temporary_smart_material_resources(
        self,
    ):
        """Remove old BakeManager_Temp resources left by interrupted saves."""
        try:
            candidates = list(
                substance_painter.resource.search(
                    "BakeManager_Temp_"
                )
            )
        except Exception:
            candidates = []

        stale = []

        for resource_object in candidates:
            try:
                name = str(
                    resource_object.identifier().name
                )
            except Exception:
                name = ""

            if name.startswith(
                "BakeManager_Temp_"
            ):
                stale.append(
                    resource_object
                )

        if not stale:
            return

        try:
            substance_painter.resource.show_resources_in_ui(
                stale
            )
            QtCore.QTimer.singleShot(
                350,
                self.send_delete_key_to_assets,
            )
        except Exception:
            pass

    def cleanup_private_smart_material_asset_duplicates(
        self,
        extra_names: Optional[list[str]] = None,
    ):
        """Remove plugin-created Smart Material duplicates from Painter Assets."""
        target_names = {
            "BakeManager_Temp_",
        }

        catalog = (
            self.private_smart_material_catalog()
        )
        target_names.update(
            catalog.keys()
        )
        target_names.update(
            os.path.splitext(
                str(
                    metadata.get(
                        "spsm_file",
                        "",
                    )
                )
            )[0]
            for metadata in catalog.values()
        )

        if extra_names:
            target_names.update(
                str(name)
                for name in extra_names
                if str(name)
            )

        candidates_by_url = {}

        for target_name in target_names:
            try:
                matches = list(
                    substance_painter.resource.search(
                        target_name
                    )
                )
            except Exception:
                matches = []

            for resource_object in matches:
                try:
                    resource_id = (
                        resource_object.identifier()
                    )
                    resource_name = str(
                        resource_id.name
                    )
                    resource_url = (
                        resource_id.url()
                    )
                except Exception:
                    continue

                is_private_duplicate = (
                    resource_name
                    in target_names
                    or resource_name.startswith(
                        "BakeSmartMat__"
                    )
                    or resource_name.startswith(
                        "BakeSmartMat_"
                    )
                    or resource_name.startswith(
                        "BakeManager_Temp_"
                    )
                )

                if is_private_duplicate:
                    candidates_by_url[
                        resource_url
                    ] = resource_object

        if not candidates_by_url:
            self.refresh_painter_resource_libraries()
            return

        try:
            substance_painter.resource.show_resources_in_ui(
                list(
                    candidates_by_url.values()
                )
            )
            QtCore.QTimer.singleShot(
                450,
                self.send_delete_key_to_assets,
            )
            QtCore.QTimer.singleShot(
                1300,
                self.refresh_painter_resource_libraries,
            )
        except Exception:
            pass

    def finalize_private_smart_material_capture(
        self,
        project_name: str,
        material_name: str,
        temporary_name: str,
        temporary_resource_url: str,
        created_after: float,
        attempt: int = 0,
    ):
        source_path = (
            self.locate_created_smart_material_file(
                temporary_name,
                created_after=created_after,
            )
        )

        if not source_path:
            if attempt < 14:
                QtCore.QTimer.singleShot(
                    350,
                    lambda: (
                        self.finalize_private_smart_material_capture(
                            project_name,
                            material_name,
                            temporary_name,
                            temporary_resource_url,
                            created_after,
                            attempt + 1,
                        )
                    ),
                )
                return

            self.status_label.setText(
                f'Smart Material "{material_name}" was created, '
                "but its .spsm file was not found."
            )
            return

        private_path = (
            self.private_smart_material_file_path(
                project_name,
                material_name,
            )
        )

        try:
            # Painter keeps the source SPSM open on Windows. Reading/copying
            # it is allowed, while moving or deleting it raises WinError 32.
            temporary_private_path = (
                private_path
                + ".copying"
            )

            if os.path.isfile(
                temporary_private_path
            ):
                os.remove(
                    temporary_private_path
                )

            shutil.copy2(
                source_path,
                temporary_private_path,
            )

            if (
                not os.path.isfile(
                    temporary_private_path
                )
                or os.path.getsize(
                    temporary_private_path
                )
                <= 0
            ):
                raise OSError(
                    "The copied SPSM is empty."
                )

            os.replace(
                temporary_private_path,
                private_path,
            )

        except OSError:
            traceback.print_exc()
            self.status_label.setText(
                "Could not copy the Smart Material into "
                "the BakeManager plugin root."
            )
            return

        self.scan_private_smart_materials()
        self.save_data()
        self.refresh_smart_material_menu()

        final_status = (
            f'Bake Smart Material saved: "{material_name}". '
            "Temporary Painter resource removed."
        )

        # The resource must be deleted before Windows releases the source
        # file handle. File cleanup is retried asynchronously afterwards.
        self.quietly_delete_painter_resource(
            temporary_resource_url
        )
        QtCore.QTimer.singleShot(
            650,
            lambda: (
                self.retry_remove_temporary_spsm(
                    source_path,
                    temporary_resource_url,
                    final_status,
                )
            ),
        )

        for delay in (
            250,
            900,
            1800,
        ):
            QtCore.QTimer.singleShot(
                delay,
                self.refresh_painter_resource_libraries,
            )

        QtCore.QTimer.singleShot(
            1500,
            lambda n=material_name, t=temporary_name: (
                self.cleanup_private_smart_material_asset_duplicates(
                    [
                        n,
                        t,
                    ]
                )
            ),
        )

    def close_smart_material_menus(
        self,
    ):
        for widget in (
            QtWidgets.QApplication
            .topLevelWidgets()
        ):
            if isinstance(
                widget,
                QtWidgets.QMenu,
            ):
                try:
                    widget.close()
                except RuntimeError:
                    pass

    def insert_smart_material_from_menu(
        self,
        name: str,
    ):
        self.close_smart_material_menus()
        self.insert_quick_smart_material(
            name
        )

    def delete_smart_material_from_menu(
        self,
        name: str,
    ):
        self.close_smart_material_menus()
        self.delete_quick_smart_material(
            name
        )

    def build_smart_material_menu_row(
        self,
        name: str,
        submenu: QtWidgets.QMenu,
    ) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget(
            submenu
        )
        row = QtWidgets.QHBoxLayout(
            widget
        )
        row.setContentsMargins(
            4,
            2,
            4,
            2,
        )
        row.setSpacing(4)

        add_button = QtWidgets.QPushButton(
            name
        )
        add_button.setFlat(True)
        add_button.setToolTip(
            "Add this Smart Material to the active Texture Set"
        )
        add_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        add_button.clicked.connect(
            lambda _checked=False, n=name: (
                self.insert_smart_material_from_menu(
                    n
                )
            )
        )
        row.addWidget(
            add_button,
            1,
        )

        delete_button = QtWidgets.QToolButton()
        delete_button.setText(
            "×"
        )
        delete_button.setFixedSize(
            24,
            22,
        )
        delete_button.setToolTip(
            "Delete this Smart Material from the plugin folder"
        )
        delete_button.clicked.connect(
            lambda _checked=False, n=name: (
                self.delete_smart_material_from_menu(
                    n
                )
            )
        )
        row.addWidget(
            delete_button
        )
        return widget

    def refresh_smart_material_menu(
        self,
    ):
        """Build the Smart Mat popup from SPSM files in the plugin root."""
        if not hasattr(
            self,
            "bake_smart_material_button",
        ):
            return

        self.scan_private_smart_materials()
        materials = (
            self.private_smart_material_catalog()
        )

        menu = QtWidgets.QMenu(
            self.bake_smart_material_button
        )
        create_action = menu.addAction(
            "Create Mat"
        )
        create_action.triggered.connect(
            self.create_quick_smart_material
        )

        add_menu = menu.addMenu(
            "Add Smart Mat"
        )

        if not materials:
            empty_action = add_menu.addAction(
                "No saved materials"
            )
            empty_action.setEnabled(
                False
            )
        else:
            for name in sorted(
                materials,
                key=str.lower,
            ):
                widget_action = (
                    QtWidgets.QWidgetAction(
                        add_menu
                    )
                )
                widget_action.setDefaultWidget(
                    self.build_smart_material_menu_row(
                        name,
                        add_menu,
                    )
                )
                add_menu.addAction(
                    widget_action
                )

        self.bake_smart_material_button.setMenu(
            menu
        )

    def create_quick_smart_material(
        self,
    ):
        """Capture exactly one selected Layers folder."""
        if not substance_painter.project.is_open():
            self.status_label.setText(
                "Open a Painter project first."
            )
            return

        try:
            stack = (
                substance_painter.textureset
                .get_active_stack()
            )
            selected = (
                layerstack.get_selected_nodes(
                    stack
                )
            )
        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not read the Layers selection."
            )
            return

        groups = [
            node
            for node in selected
            if self.node_is_group(
                node
            )
        ]

        if len(groups) != 1:
            self.status_label.setText(
                "Select exactly one folder/group in Layers."
            )
            return

        default_name = (
            self.layer_node_name(
                groups[0]
            )
            or "Smart Mat"
        )
        name, accepted = (
            QtWidgets.QInputDialog.getText(
                self,
                "Add Smart Mat",
                "Smart Mat name:",
                text=default_name,
            )
        )

        if (
            not accepted
            or not str(name).strip()
        ):
            return

        name = str(
            name
        )

        if not self.smart_material_name_is_file_safe(
            name
        ):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Smart Mat name",
                "Use a name without \\ / : * ? \" < > |, "
                "and do not start or end it with spaces.",
            )
            return

        private_path = (
            self.private_smart_material_file_path(
                "",
                name,
            )
        )

        if os.path.isfile(
            private_path
        ):
            answer = QtWidgets.QMessageBox.question(
                self,
                "Replace Smart Mat",
                f'A Smart Mat named "{name}" already exists. Replace it?',
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel,
            )

            if (
                answer
                != QtWidgets.QMessageBox.StandardButton.Yes
            ):
                return

        created_after = time.time()
        temporary_name = (
            "BakeManager_Temp_"
            + str(
                int(
                    created_after
                    * 1000
                )
            )
        )

        self.ensure_temporary_smart_material_ignore_rule()
        self.delete_stale_temporary_smart_material_resources()
        self.purge_bake_manager_temporary_spsm_files()

        try:
            resource_object = (
                layerstack.create_smart_material(
                    groups[0],
                    temporary_name,
                )
            )
            resource_url = (
                resource_object.identifier().url()
            )
        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not create the temporary Smart Material."
            )
            return

        self.status_label.setText(
            f'Adding Smart Mat: "{name}"...'
        )
        QtCore.QTimer.singleShot(
            250,
            lambda: (
                self.finalize_private_smart_material_capture(
                    self.current_bake_project_name(),
                    name,
                    temporary_name,
                    resource_url,
                    created_after,
                )
            ),
        )

    def insert_quick_smart_material(
        self,
        name: str,
    ):
        """Insert one saved Smart Material into every Texture Set."""
        metadata = (
            self.get_private_smart_material_metadata(
                name
            )
        )

        if not isinstance(
            metadata,
            dict,
        ):
            return

        spsm_path = os.path.join(
            self.private_smart_material_directory(),
            os.path.basename(
                str(
                    metadata.get(
                        "spsm_file",
                        "",
                    )
                )
            ),
        )

        if not os.path.isfile(
            spsm_path
        ):
            self.status_label.setText(
                "The Smart Material file could not be found."
            )
            return

        try:
            texture_sets = list(
                substance_painter.textureset
                .all_texture_sets()
            )
        except Exception:
            traceback.print_exc()
            texture_sets = []

        if not texture_sets:
            self.status_label.setText(
                "No Texture Sets are available."
            )
            return

        try:
            resource_id = (
                self.import_private_smart_material_resource(
                    spsm_path
                )
            )
            resource_url = resource_id.url()

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not import the Smart Material. "
                "See Python Console."
            )
            return

        inserted_texture_sets = 0
        inserted_stacks = 0
        assigned_sources = 0
        failed_stacks = 0

        for texture_set in texture_sets:
            texture_set_name = (
                self.texture_set_display_name(
                    texture_set
                )
            )

            try:
                stacks = list(
                    texture_set.all_stacks()
                )
            except Exception:
                traceback.print_exc()
                stacks = []

            if not stacks:
                failed_stacks += 1
                continue

            set_inserted = False

            for stack in stacks:
                try:
                    position = (
                        layerstack.InsertPosition
                        .from_textureset_stack(
                            stack
                        )
                    )
                    before_roots = list(
                        layerstack.get_root_layer_nodes(
                            stack
                        )
                    )
                    before_ids = {
                        self.layer_node_uid(
                            node
                        )
                        for node in before_roots
                    }

                    with layerstack.ScopedModification(
                        "Insert private Bake Smart Material"
                    ):
                        inserted_result = (
                            layerstack.insert_smart_material(
                                position,
                                resource_id,
                            )
                        )

                    after_roots = list(
                        layerstack.get_root_layer_nodes(
                            stack
                        )
                    )
                    new_roots = [
                        node
                        for node in after_roots
                        if self.layer_node_uid(
                            node
                        )
                        not in before_ids
                    ]
                    inserted_group = None

                    if (
                        inserted_result is not None
                        and self.node_is_group(
                            inserted_result
                        )
                    ):
                        inserted_group = (
                            inserted_result
                        )
                    else:
                        inserted_group = next(
                            (
                                node
                                for node in new_roots
                                if self.node_is_group(
                                    node
                                )
                            ),
                            None,
                        )

                    if inserted_group is not None:
                        with layerstack.ScopedModification(
                            "Name Bake Smart Material root"
                        ):
                            inserted_group.set_name(
                                texture_set_name
                            )

                    assigned_sources += (
                        self.auto_assign_all_bake_records_for_texture_set(
                            texture_set_name,
                            root_group=inserted_group,
                        )
                    )
                    inserted_stacks += 1
                    set_inserted = True

                except Exception:
                    traceback.print_exc()
                    failed_stacks += 1

            if set_inserted:
                inserted_texture_sets += 1

        if inserted_stacks <= 0:
            final_status = (
                f'Could not insert "{name}" into any Texture Set. '
                "Temporary Painter asset removed."
            )
        else:
            final_status = (
                f'Inserted "{name}" into '
                f"{inserted_texture_sets} Texture Set(s) "
                f"and {inserted_stacks} stack(s); "
                f"assigned {assigned_sources} bake source(s)."
            )

            if failed_stacks:
                final_status += (
                    f" Failed stack(s): {failed_stacks}."
                )
            else:
                final_status += (
                    " Temporary Painter asset removed."
                )

        QtCore.QTimer.singleShot(
            500,
            lambda: (
                self.quietly_delete_painter_resource(
                    resource_url,
                    final_status=final_status,
                )
            ),
        )

    def delete_quick_smart_material(
        self,
        name: str,
    ):
        metadata = (
            self.get_private_smart_material_metadata(
                name
            )
        )

        if not isinstance(
            metadata,
            dict,
        ):
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete Smart Mat",
            f'Delete "{name}" from the plugin folder?',
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )

        if (
            answer
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return

        file_path = os.path.join(
            self.private_smart_material_directory(),
            os.path.basename(
                str(
                    metadata.get(
                        "spsm_file",
                        "",
                    )
                )
            ),
        )

        try:
            if os.path.isfile(
                file_path
            ):
                os.remove(
                    file_path
                )
        except OSError:
            traceback.print_exc()
            self.status_label.setText(
                "Could not delete the Smart Material file."
            )
            return

        self.scan_private_smart_materials()
        self.save_data()
        self.refresh_smart_material_menu()
        self.cleanup_private_smart_material_asset_duplicates(
            [
                name
            ]
        )

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    @staticmethod
    def default_data() -> dict[str, Any]:
        return {
            "version": 2,
            "folders": [],
            "resources": {},
            "hidden_resource_urls": [],
            "manually_deleted_resource_urls": [],
            "ui_state": {
                "current_folder": "",
                "search": "",
                "suffix_filter": "",
            },
            "marmoset_bridge": {
                "toolbag_exe": "",
                "high_poly_paths": [],
            },
            "custom_suffixes": [],
            "bake_manager": {
                "projects": {
                    "Project": {
                        "setups": {},
                        "smart_materials": {},
                        "checked_setups": [],
                    }
                },
                "current_project": "Project",
            },
        }

    def legacy_project_data_path(self) -> Optional[str]:
        """Return the former JSON location next to the SPP project."""
        if not substance_painter.project.is_open():
            return None

        project_path = substance_painter.project.file_path()

        if not project_path:
            return None

        base_path, _extension = os.path.splitext(
            str(project_path)
        )

        return base_path + "_custom_asset_manager.json"

    def project_data_path(self) -> Optional[str]:
        """Store manager data inside the same *_Bakes folder as textures."""
        cache_dir = self.preview_cache_dir()

        if not cache_dir:
            return None

        project_path = substance_painter.project.file_path()

        if not project_path:
            return None

        project_name = os.path.splitext(
            os.path.basename(
                str(project_path)
            )
        )[0]

        return os.path.join(
            cache_dir,
            project_name + "_custom_asset_manager.json",
        )

    def read_data(self) -> dict[str, Any]:
        path = self.project_data_path()

        if not path:
            return self.default_data()

        read_path = path

        if not os.path.isfile(read_path):
            legacy_path = self.legacy_project_data_path()

            if (
                legacy_path
                and os.path.isfile(legacy_path)
            ):
                read_path = legacy_path
            else:
                return self.default_data()

        try:
            with open(read_path, "r", encoding="utf-8") as stream:
                data = json.load(stream)

            if data.get("version") != 2:
                return self.default_data()

            data.setdefault("folders", [])
            data.setdefault("resources", {})
            data.setdefault("hidden_resource_urls", [])
            data.setdefault("manually_deleted_resource_urls", [])
            data.setdefault(
                "ui_state",
                {
                    "current_folder": "",
                    "search": "",
                    "suffix_filter": "",
                },
            )
            data["ui_state"].setdefault(
                "suffix_filter",
                "",
            )
            data.setdefault(
                "marmoset_bridge",
                {
                    "toolbag_exe": "",
                    "high_poly_paths": [],
                },
            )
            data.setdefault(
                "custom_suffixes",
                [],
            )
            data.setdefault(
                "bake_manager",
                {
                    "projects": {
                        "Project": {
                            "setups": {},
                            "smart_materials": {},
                            "checked_setups": [],
                        }
                    },
                    "current_project": "Project",
                },
            )

            manager_data = data["bake_manager"]
            manager_data.setdefault("projects", {})
            manager_data.setdefault("current_project", "Project")
            manager_data["projects"].setdefault(
                "Project",
                {
                    "setups": {},
                    "smart_materials": {},
                    "checked_setups": [],
                },
            )

            for project_data in manager_data["projects"].values():
                project_data.setdefault("setups", {})
                project_data.setdefault("smart_materials", {})
                project_data.setdefault("checked_setups", [])

            return data

        except (OSError, json.JSONDecodeError):
            traceback.print_exc()
            return self.default_data()

    @staticmethod
    def normalized_data_path(
        path: Optional[str],
    ) -> Optional[str]:
        if not path:
            return None

        return os.path.normcase(
            os.path.abspath(
                str(path)
            )
        )

    def save_data(self):
        if self._loading:
            return

        # Never write shared Projects during the brief interval in which
        # Painter has changed scenes but load_manager() has not yet loaded
        # BakeProject files. Previously this could replace valid Setups with
        # an empty Project from the new scene.
        if self._shared_projects_ready:
            self.save_shared_bake_projects(
                show_error=False
            )

        path = self.project_data_path()

        if not path:
            return

        normalized_path = self.normalized_data_path(
            path
        )

        # Never write data from the previous project into a newly opened one.
        # load_manager() sets this marker only after the correct sidecar file
        # has been loaded.
        if (
            self._loaded_project_data_path is None
            or normalized_path
            != self._loaded_project_data_path
        ):
            return

        self._data["ui_state"] = {
            "current_folder": self.current_folder_path(),
            "search": self.search_edit.text(),
            "suffix_filter": self._active_suffix_filter,
        }

        try:
            os.makedirs(
                os.path.dirname(path),
                exist_ok=True,
            )

            with open(path, "w", encoding="utf-8") as stream:
                json.dump(
                    self._data,
                    stream,
                    ensure_ascii=False,
                    indent=4,
                )

            # Migrate projects made with older plugin versions. The old
            # sidecar is removed only after the new file has been saved.
            legacy_path = self.legacy_project_data_path()

            if (
                legacy_path
                and self.normalized_data_path(legacy_path)
                != self.normalized_data_path(path)
                and os.path.isfile(legacy_path)
            ):
                try:
                    os.remove(legacy_path)
                except OSError:
                    traceback.print_exc()

        except OSError:
            traceback.print_exc()
            self.status_label.setText(
                "Could not save the manager JSON file."
            )

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def remove_obsolete_root_folders(self):
        """Move Texture Set folders to Project root and remove old categories."""
        obsolete_roots = {
            DEFAULT_BAKE_FOLDER,
            DEFAULT_IMPORTED_FOLDER,
        }

        migrated_folders = []

        for folder_path in self._data.setdefault(
            "folders",
            [],
        ):
            normalized = self.normalize_folder_path(
                folder_path
            )

            if not normalized or normalized in obsolete_roots:
                continue

            migrated_path = normalized

            for root_name in obsolete_roots:
                prefix = root_name + "/"

                if normalized.startswith(prefix):
                    migrated_path = normalized[len(prefix):]
                    break

            if (
                migrated_path
                and migrated_path not in migrated_folders
            ):
                migrated_folders.append(migrated_path)

        self._data["folders"] = migrated_folders

        for record in self._data.setdefault(
            "resources",
            {},
        ).values():
            current_folder = self.normalize_folder_path(
                record.get("folder", "")
            )

            if current_folder in obsolete_roots:
                record["folder"] = ""
                continue

            for root_name in obsolete_roots:
                prefix = root_name + "/"

                if current_folder.startswith(prefix):
                    record["folder"] = current_folder[len(prefix):]
                    break

        self._current_folder_path = ""

    def reset_new_unsaved_project_state(self):
        """Clear data inherited from the previously opened Painter project."""
        self._loading = True
        self._shared_projects_ready = False

        try:
            self._data = self.default_data()
            self.apply_shared_bake_projects(
                create_if_missing=True
            )
            self._shared_projects_ready = True
            self.apply_shared_bake_smart_mat(
                create_if_missing=True
            )
            self._loaded_project_data_path = None
            self._current_folder_path = ""
            self._setup_disabled_bakers.clear()
            self._setup_row_checks.clear()
            self._setup_row_widgets.clear()
            self._bake_setup_queue = []
            self._bake_setup_queue_index = -1
            self._bake_setup_running = False
            self._last_mesh_map_signature = None
            self._painter_was_busy = False
            self._preview_cache.clear()

            self.search_edit.blockSignals(True)

            try:
                self.search_edit.clear()
            finally:
                self.search_edit.blockSignals(False)

            self.apply_suffix_filter_state(
                "",
                refresh=False,
                save=False,
            )

            self.asset_list.clear()
            self.breadcrumb_label.setText(
                "Project"
            )
            self.refresh_bake_setup_ui()

        finally:
            self._loading = False

        self.status_label.setText(
            "New project: shared Projects, Setups and Bake Layer "
            "Templates loaded from JSON. Save the Painter project to "
            "enable scene-specific assets and folders."
        )

    def load_manager(self):
        if not substance_painter.project.is_open():
            self._loaded_project_data_path = None
            self.status_label.setText(
                "Open a project, then right-click and choose Refresh."
            )
            return

        data_path = self.project_data_path()

        if not data_path:
            self.reset_new_unsaved_project_state()
            return

        self._loading = True
        self._shared_projects_ready = False

        try:
            self._data = self.read_data()
            self.apply_shared_bake_projects(
                create_if_missing=True
            )
            self._shared_projects_ready = True
            self.apply_shared_bake_smart_mat(
                create_if_missing=True
            )
            self.ensure_default_folders()
            self.organize_generated_files_on_disk()
            self.remove_obsolete_root_folders()

            ui_state = self._data.setdefault(
                "ui_state",
                {
                    "current_folder": "",
                    "search": "",
                    "suffix_filter": "",
                },
            )

            restored_folder = self.normalize_folder_path(
                ui_state.get(
                    "current_folder",
                    "",
                )
            )

            existing_folders = {
                self.normalize_folder_path(path)
                for path in self._data.get(
                    "folders",
                    [],
                )
            }

            if (
                restored_folder
                and restored_folder not in existing_folders
            ):
                restored_folder = ""

            self._current_folder_path = restored_folder

            restored_search = str(
                ui_state.get(
                    "search",
                    "",
                )
            )

            self.search_edit.blockSignals(True)

            try:
                self.search_edit.setText(
                    restored_search
                )
            finally:
                self.search_edit.blockSignals(False)

            restored_suffix_filter = str(
                ui_state.get(
                    "suffix_filter",
                    "",
                )
            ).upper()

            if restored_suffix_filter not in (
                "",
                "N",
                "AO",
                "CV",
                "ID",
            ):
                restored_suffix_filter = ""

            self.apply_suffix_filter_state(
                restored_suffix_filter,
                refresh=False,
                save=False,
            )

            self.synchronize_project_resources()
            self.populate_folder_tree()

            self._loaded_project_data_path = (
                self.normalized_data_path(
                    data_path
                )
            )
            self._last_mesh_map_signature = None
            self._painter_was_busy = False

            # A new Painter project starts with an empty Bake Project.
            # bake_templates.json is no longer imported automatically.
            self.refresh_bake_setup_ui()

        finally:
            self._loading = False

        self.save_data()

    def refresh_and_generate_previews(self):
        """Refresh project resources and regenerate bake-map previews."""
        self.refresh_manager()

        QtCore.QTimer.singleShot(
            150,
            lambda: self.generate_bake_map_previews(
                automatic=False,
                delete_from_assets_after_export=False,
            ),
        )

    def refresh_manager(self):
        if not substance_painter.project.is_open():
            QtWidgets.QMessageBox.information(
                self,
                "Bake Manager",
                "Open a Substance Painter project first.",
            )
            return

        current_data_path = self.normalized_data_path(
            self.project_data_path()
        )

        if (
            current_data_path is None
            or current_data_path
            != self._loaded_project_data_path
        ):
            self.load_manager()
            self.initialize_bake_watcher()
            return

        try:
            moved_files = (
                self.organize_generated_files_on_disk()
            )
            self.synchronize_project_resources()
            imported_marmoset = self.import_marmoset_manifest(
                force=True
            )
            self.populate_folder_tree()
            self.refresh_bake_setup_ui()
            (
                checked_assignments,
                repaired_assignments,
            ) = self.refresh_bake_layer_assignments()

            status_parts = [
                "Project resources refreshed"
            ]

            if moved_files:
                status_parts.append(
                    f"organized {moved_files} file(s)"
                )

            if imported_marmoset:
                status_parts.append(
                    f"received {imported_marmoset} Marmoset map(s)"
                )

            if repaired_assignments:
                status_parts.append(
                    f"repaired {repaired_assignments} layer assignment(s)"
                )
            elif checked_assignments:
                status_parts.append(
                    f"checked {checked_assignments} bake assignment(s)"
                )

            self.status_label.setText(
                "; ".join(status_parts) + "."
            )

            self.save_data()

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Refresh failed. See Python Console."
            )

    def ensure_default_folders(self):
        """Initialize folder storage without fixed root categories."""
        self._data.setdefault(
            "folders",
            [],
        )

    def synchronize_project_resources(self):
        resources_data = self._data.setdefault(
            "resources",
            {},
        )

        hidden_urls = set(
            self._data.setdefault(
                "hidden_resource_urls",
                [],
            )
        )

        project_ids = (
            substance_painter.resource.list_project_resources()
        )

        active_resources = []

        # Existing exported/archived files already represented by tiles.
        file_stem_to_urls = {}

        for existing_url, existing_record in resources_data.items():
            preview_path = existing_record.get(
                "preview_path"
            )

            if not preview_path:
                continue

            stem = os.path.splitext(
                os.path.basename(
                    str(preview_path)
                )
            )[0].lower()

            file_stem_to_urls.setdefault(
                stem,
                set(),
            ).add(existing_url)

        for resource_id in project_ids:
            context = str(resource_id.context)

            if not context.startswith("project"):
                continue

            url = resource_id.url()

            # Resources imported only to feed Fill Layers or Mesh Map slots
            # must not appear as additional manager tiles.
            if url in hidden_urls:
                resources_data.pop(url, None)
                continue

            resource_stem = str(
                resource_id.name
            ).lower()

            represented_urls = file_stem_to_urls.get(
                resource_stem,
                set(),
            )

            # Cleanup for duplicates created by earlier plugin versions:
            # if a real exported file with this exact name is already shown,
            # hide the newly imported Painter copy.
            if represented_urls and url not in represented_urls:
                hidden_urls.add(url)
                resources_data.pop(url, None)
                continue

            active_resources.append(
                (
                    url,
                    resource_id,
                )
            )

        self._data["hidden_resource_urls"] = sorted(
            hidden_urls
        )

        active_urls = {
            url
            for url, _resource_id in active_resources
        }

        for url, resource_id in active_resources:
            if url not in resources_data:
                folder = ""

                resources_data[url] = {
                    "original_name": resource_id.name,
                    "alias": resource_id.name,
                    "folder": folder,
                    "type": self.detect_resource_type(
                        resource_id.name
                    ),
                }

            record = resources_data[url]

            record["original_name"] = resource_id.name
            record.setdefault("alias", resource_id.name)
            record.setdefault(
                "folder",
                "",
            )
            record["type"] = self.detect_resource_type(
                resource_id.name
            )
            record["painter_active"] = True

        stale_urls = []

        for url, record in list(resources_data.items()):
            if url in hidden_urls:
                stale_urls.append(url)
                continue

            is_active_in_painter = url in active_urls
            preview_path = record.get("preview_path")
            has_disk_file = bool(
                preview_path
                and os.path.isfile(str(preview_path))
            )

            record["painter_active"] = is_active_in_painter
            record["available"] = (
                is_active_in_painter
                or has_disk_file
            )

            if not is_active_in_painter and not has_disk_file:
                stale_urls.append(url)

        for url in stale_urls:
            resources_data.pop(url, None)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def is_bake_resource(name: str) -> bool:
        lower_name = name.lower()

        if any(word in lower_name for word in BAKE_KEYWORDS):
            return True

        return (
            lower_name.endswith("_ao")
            or "_ao_" in lower_name
            or lower_name.endswith("_n")
            or "_normal_" in lower_name
        )

    @staticmethod
    def detect_resource_type(name: str) -> str:
        lower_name = name.lower()
        stem = os.path.splitext(
            os.path.basename(lower_name)
        )[0]

        if (
            "bent normal" in lower_name
            or "bentnormal" in lower_name
            or stem.endswith("_bn")
        ):
            return "Bent Normals"

        if (
            "world space normal" in lower_name
            or "worldspace normal" in lower_name
            or stem.endswith("_wsn")
        ):
            return "World Space Normal"

        if (
            "ambient occlusion" in lower_name
            or stem.endswith("_ao")
            or "_ao_" in lower_name
        ):
            return "Ambient Occlusion"

        if (
            "normal map" in lower_name
            or stem.endswith("_n")
            or "_normal_" in lower_name
        ):
            return "Normal"

        if (
            "curvature" in lower_name
            or stem.endswith("_c")
        ):
            return "Curvature"

        if (
            "thickness" in lower_name
            or stem.endswith("_t")
        ):
            return "Thickness"

        if (
            "position" in lower_name
            or stem.endswith("_p")
        ):
            return "Position"

        if (
            "height" in lower_name
            or stem.endswith("_h")
        ):
            return "Height"

        if (
            "opacity" in lower_name
            or "transparency" in lower_name
            or stem.endswith("_o")
        ):
            return "Opacity"

        if (
            "id map" in lower_name
            or stem.endswith("_id")
        ):
            return "ID Map"

        return "Texture"

    # ------------------------------------------------------------------
    # Flat folder browser
    # ------------------------------------------------------------------

    def populate_folder_tree(
        self,
        preferred_path: Optional[str] = None,
    ):
        """Compatibility wrapper retained for older internal calls."""
        if preferred_path is not None:
            normalized = self.normalize_folder_path(
                preferred_path
            )
            self._current_folder_path = normalized

        self.populate_asset_tiles()

    def current_folder_path(self) -> str:
        return self._current_folder_path

    @staticmethod
    def normalize_folder_path(path: str) -> str:
        return "/".join(
            part.strip()
            for part in str(path).replace("\\", "/").split("/")
            if part.strip()
        )

    def open_folder(self, folder_path: str):
        self._current_folder_path = self.normalize_folder_path(
            folder_path
        )
        self.populate_asset_tiles()

    def open_parent_folder(self):
        current = self.current_folder_path()

        if not current:
            return

        parent = "/".join(current.split("/")[:-1])
        self.open_folder(parent)

    def direct_child_folders(
        self,
        parent_path: str,
    ) -> list[str]:
        parent_path = self.normalize_folder_path(
            parent_path
        )
        result = []

        for folder_path in self._data.get(
            "folders",
            [],
        ):
            normalized = self.normalize_folder_path(
                folder_path
            )

            if not normalized:
                continue

            parent = "/".join(
                normalized.split("/")[:-1]
            )

            if parent == parent_path:
                result.append(normalized)

        return sorted(
            set(result),
            key=lambda value: value.lower(),
        )

    # ------------------------------------------------------------------
    # Tiles
    # ------------------------------------------------------------------

    def set_suffix_filter(
        self,
        filter_key: str,
        checked: bool,
    ):
        filter_key = str(
            filter_key
        ).upper()

        if checked:
            active_filter = filter_key
        elif (
            self._active_suffix_filter
            == filter_key
        ):
            active_filter = ""
        else:
            active_filter = (
                self._active_suffix_filter
            )

        self.apply_suffix_filter_state(
            active_filter,
            refresh=True,
            save=True,
        )

    def apply_suffix_filter_state(
        self,
        filter_key: str,
        refresh: bool = True,
        save: bool = True,
    ):
        filter_key = str(
            filter_key
        ).upper()

        if filter_key not in (
            "",
            "N",
            "AO",
            "CV",
            "ID",
        ):
            filter_key = ""

        self._active_suffix_filter = (
            filter_key
        )

        for key, button in (
            self.suffix_filter_buttons.items()
        ):
            button.blockSignals(True)

            try:
                button.setChecked(
                    key == filter_key
                )
            finally:
                button.blockSignals(False)

        if refresh:
            self.populate_asset_tiles()

        if save:
            self.save_data()

    @staticmethod
    def filename_suffix_tokens(
        record: dict[str, Any],
    ) -> set[str]:
        preview_path = record.get(
            "preview_path",
            "",
        )
        source_name = (
            os.path.splitext(
                os.path.basename(
                    str(preview_path)
                )
            )[0]
            if preview_path
            else str(
                record.get(
                    "alias",
                    record.get(
                        "original_name",
                        "",
                    ),
                )
            )
        )

        return {
            token.upper()
            for token in re.split(
                r"[_\-\s.]+",
                source_name,
            )
            if token
        }

    def record_matches_suffix_filter(
        self,
        record: dict[str, Any],
    ) -> bool:
        filter_key = (
            self._active_suffix_filter
        )

        if not filter_key:
            return True

        resource_type = str(
            record.get(
                "type",
                "",
            )
        ).strip().lower()
        tokens = self.filename_suffix_tokens(
            record
        )

        if filter_key == "N":
            return (
                resource_type == "normal"
                or "N" in tokens
            )

        if filter_key == "AO":
            return (
                resource_type
                == "ambient occlusion"
                or "AO" in tokens
            )

        if filter_key == "CV":
            return (
                resource_type == "curvature"
                or "C" in tokens
                or "CV" in tokens
            )

        if filter_key == "ID":
            return (
                resource_type in (
                    "id",
                    "id map",
                )
                or "ID" in tokens
            )

        return True

    def populate_asset_tiles(self, *_args):
        folder_path = self.current_folder_path()
        query = self.search_edit.text().strip().lower()

        self.asset_list.clear()

        visible_folder_count = 0
        visible_resource_count = 0

        # Parent-folder shortcut.
        if folder_path and not query:
            parent_item = QtWidgets.QListWidgetItem()
            parent_item.setText("..")
            parent_item.setToolTip("Go to parent folder")
            parent_item.setData(
                ROLE_KIND,
                KIND_FOLDER,
            )
            parent_item.setData(
                ROLE_FOLDER_PATH,
                "/".join(folder_path.split("/")[:-1]),
            )
            parent_item.setIcon(
                self.create_folder_icon(
                    is_parent=True
                )
            )
            self.asset_list.addItem(parent_item)
            visible_folder_count += 1

        # Folder tiles.
        for child_path in self.direct_child_folders(
            folder_path
        ):
            folder_name = child_path.split("/")[-1]

            if query and query not in folder_name.lower():
                continue

            folder_item = QtWidgets.QListWidgetItem()
            folder_item.setText(folder_name)
            folder_item.setToolTip(
                f"Folder: {child_path}"
            )
            folder_item.setData(
                ROLE_KIND,
                KIND_FOLDER,
            )
            folder_item.setData(
                ROLE_FOLDER_PATH,
                child_path,
            )
            folder_item.setIcon(
                self.build_folder_icon(
                    child_path
                )
            )

            # Folder tiles are drop targets, not drag sources.
            folder_item.setFlags(
                folder_item.flags()
                & ~QtCore.Qt.ItemFlag.ItemIsDragEnabled
            )

            self.asset_list.addItem(folder_item)
            visible_folder_count += 1

        resources = self._data.get(
            "resources",
            {},
        )
        matching_items = []

        for url, record in resources.items():
            resource_folder = self.normalize_folder_path(
                record.get("folder", "")
            )

            if resource_folder != folder_path:
                continue

            alias = record.get(
                "alias",
                record.get("original_name", "Resource"),
            )
            resource_type = record.get(
                "type",
                "Texture",
            )

            search_text = (
                alias
                + " "
                + record.get("original_name", "")
                + " "
                + resource_type
            ).lower()

            if query and query not in search_text:
                continue

            if not self.record_matches_suffix_filter(
                record
            ):
                continue

            matching_items.append(
                (
                    alias.lower(),
                    url,
                    record,
                )
            )

        matching_items.sort(
            key=lambda entry: entry[0]
        )

        for _sort_name, url, record in matching_items:
            item = QtWidgets.QListWidgetItem()

            alias = record.get(
                "alias",
                record.get("original_name", "Resource"),
            )

            item.setText(alias)
            item.setToolTip(
                (
                    f"Original name: "
                    f"{record.get('original_name', '')}\n"
                    f"Type: {record.get('type', 'Texture')}\n"
                    f"Folder: {record.get('folder', '')}\n"
                    f"URL: {url}"
                )
            )

            item.setData(
                ROLE_KIND,
                KIND_RESOURCE,
            )
            item.setData(
                ROLE_RESOURCE_URL,
                url,
            )
            item.setData(
                ROLE_ORIGINAL_NAME,
                record.get("original_name", ""),
            )

            preview_path = record.get(
                "preview_path"
            )

            if (
                preview_path
                and os.path.isfile(
                    str(preview_path)
                )
            ):
                item.setData(
                    ROLE_DRAG_PATH,
                    os.path.normpath(
                        str(preview_path)
                    ),
                )

            item.setIcon(
                self.build_asset_icon(record)
            )

            if not record.get(
                "available",
                True,
            ):
                item.setFlags(
                    item.flags()
                    & ~QtCore.Qt.ItemFlag.ItemIsEnabled
                )

            self.asset_list.addItem(item)
            visible_resource_count += 1

        title = (
            "Project"
            if not folder_path
            else "Project / " + folder_path
        )
        self.breadcrumb_label.setText(title)

        filter_status = (
            f" · filter: {self._active_suffix_filter}"
            if self._active_suffix_filter
            else ""
        )

        self.status_label.setText(
            f"{visible_folder_count} folder(s), "
            f"{visible_resource_count} texture(s)"
            + filter_status
        )

    def folder_preview_path(
        self,
        folder_path: str,
    ) -> Optional[str]:
        previews = self._data.setdefault(
            "folder_previews",
            {},
        )

        preview_path = previews.get(
            self.normalize_folder_path(
                folder_path
            )
        )

        if (
            preview_path
            and os.path.isfile(
                str(preview_path)
            )
        ):
            return os.path.normpath(
                str(preview_path)
            )

        return None

    def build_folder_icon(
        self,
        folder_path: str,
    ) -> QtGui.QIcon:
        """Use a manual 3D viewport screenshot instead of the folder icon."""
        preview_path = self.folder_preview_path(
            folder_path
        )

        if not preview_path:
            return self.create_folder_icon()

        pixmap = QtGui.QPixmap(
            preview_path
        )

        if pixmap.isNull():
            return self.create_folder_icon()

        size = 112
        canvas = QtGui.QPixmap(
            size,
            size,
        )
        canvas.fill(
            QtCore.Qt.GlobalColor.transparent
        )

        painter = QtGui.QPainter(canvas)

        try:
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.Antialiasing,
                True,
            )
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.SmoothPixmapTransform,
                True,
            )

            source_size = min(
                pixmap.width(),
                pixmap.height(),
            )
            source_rect = QtCore.QRect(
                (pixmap.width() - source_size) // 2,
                (pixmap.height() - source_size) // 2,
                source_size,
                source_size,
            )

            target_rect = QtCore.QRectF(
                3,
                3,
                size - 6,
                size - 6,
            )

            painter.setPen(
                QtCore.Qt.PenStyle.NoPen
            )
            painter.setBrush(
                QtGui.QColor(
                    25,
                    25,
                    25,
                )
            )
            painter.drawRoundedRect(
                target_rect,
                6,
                6,
            )

            clip_path = QtGui.QPainterPath()
            clip_path.addRoundedRect(
                target_rect,
                6,
                6,
            )
            painter.setClipPath(
                clip_path
            )
            painter.drawPixmap(
                target_rect,
                pixmap,
                QtCore.QRectF(source_rect),
            )
            painter.setClipping(False)

            # Subtle frame so the screenshot reads as a folder tile.
            gradient = QtGui.QLinearGradient(
                0,
                0,
                0,
                size,
            )
            gradient.setColorAt(
                0.0,
                QtGui.QColor("#caa85d"),
            )
            gradient.setColorAt(
                0.5,
                QtGui.QColor("#967135"),
            )
            gradient.setColorAt(
                1.0,
                QtGui.QColor("#5f451f"),
            )

            painter.setPen(
                QtGui.QPen(
                    QtGui.QBrush(gradient),
                    3.0,
                )
            )
            painter.setBrush(
                QtCore.Qt.BrushStyle.NoBrush
            )
            painter.drawRoundedRect(
                QtCore.QRectF(
                    2,
                    2,
                    size - 4,
                    size - 4,
                ),
                6,
                6,
            )

        finally:
            painter.end()

        return QtGui.QIcon(canvas)

    def create_folder_icon(
        self,
        is_parent: bool = False,
    ) -> QtGui.QIcon:
        """Create a simple folder thumbnail matching the tile browser."""
        size = 112
        canvas = QtGui.QPixmap(
            size,
            size,
        )
        canvas.fill(
            QtCore.Qt.GlobalColor.transparent
        )

        painter = QtGui.QPainter(canvas)

        try:
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.Antialiasing,
                True,
            )

            body_color = QtGui.QColor(
                196,
                157,
                67,
            )
            tab_color = QtGui.QColor(
                222,
                185,
                90,
            )
            outline_color = QtGui.QColor(
                90,
                72,
                35,
            )

            painter.setPen(
                QtGui.QPen(
                    outline_color,
                    2,
                )
            )

            tab_rect = QtCore.QRectF(
                18,
                27,
                38,
                18,
            )
            body_rect = QtCore.QRectF(
                12,
                38,
                88,
                58,
            )

            painter.setBrush(tab_color)
            painter.drawRoundedRect(
                tab_rect,
                5,
                5,
            )

            painter.setBrush(body_color)
            painter.drawRoundedRect(
                body_rect,
                7,
                7,
            )

            if is_parent:
                painter.setPen(
                    QtGui.QPen(
                        QtGui.QColor(35, 35, 35),
                        7,
                        QtCore.Qt.PenStyle.SolidLine,
                        QtCore.Qt.PenCapStyle.RoundCap,
                        QtCore.Qt.PenJoinStyle.RoundJoin,
                    )
                )
                painter.drawLine(
                    QtCore.QPointF(69, 67),
                    QtCore.QPointF(44, 67),
                )
                painter.drawLine(
                    QtCore.QPointF(44, 67),
                    QtCore.QPointF(56, 55),
                )
                painter.drawLine(
                    QtCore.QPointF(44, 67),
                    QtCore.QPointF(56, 79),
                )

        finally:
            painter.end()

        return QtGui.QIcon(canvas)

    def build_asset_icon(
        self,
        record: dict[str, Any],
    ) -> QtGui.QIcon:
        """Return a thumbnail with an optional subtle gradient frame."""
        available = record.get("available", True)
        preview_path = record.get("preview_path")
        base_icon = None

        if preview_path and os.path.isfile(preview_path):
            base_icon = self.load_preview_icon(
                preview_path,
                available,
            )

        if base_icon is None:
            base_icon = self.create_type_thumbnail(
                record.get("type", "Texture"),
                available=available,
            )

        color_label = str(
            record.get("color_label", "none")
        ).lower()

        return self.apply_color_label_frame(
            base_icon,
            color_label,
        )

    def apply_color_label_frame(
        self,
        base_icon: QtGui.QIcon,
        color_label: str,
    ) -> QtGui.QIcon:
        """Draw a flat single-color frame around a texture icon."""
        palette = COLOR_LABELS.get(
            color_label,
        )

        if palette is None:
            return base_icon

        size = 112
        canvas = QtGui.QPixmap(
            size,
            size,
        )
        canvas.fill(
            QtCore.Qt.GlobalColor.transparent
        )

        painter = QtGui.QPainter(canvas)

        try:
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.Antialiasing,
                True,
            )

            preview_rect = QtCore.QRect(
                4,
                4,
                size - 8,
                size - 8,
            )

            preview = base_icon.pixmap(
                preview_rect.size()
            )

            painter.drawPixmap(
                preview_rect,
                preview,
            )

            # Use the middle palette color as a clean, flat label.
            _light_color, frame_color, _dark_color = palette

            frame_pen = QtGui.QPen(
                frame_color,
                3.0,
            )
            frame_pen.setJoinStyle(
                QtCore.Qt.PenJoinStyle.RoundJoin
            )
            frame_pen.setCapStyle(
                QtCore.Qt.PenCapStyle.RoundCap
            )

            painter.setPen(
                frame_pen
            )
            painter.setBrush(
                QtCore.Qt.BrushStyle.NoBrush
            )
            painter.drawRoundedRect(
                QtCore.QRectF(
                    2.0,
                    2.0,
                    size - 4.0,
                    size - 4.0,
                ),
                4.0,
                4.0,
            )

        finally:
            painter.end()

        return QtGui.QIcon(canvas)

    def load_preview_icon(
        self,
        path: str,
        available: bool,
    ) -> Optional[QtGui.QIcon]:
        """Load an image file into a 112x112 thumbnail icon (cached by mtime)."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None

        cache_key = (path, available)
        cached = self._preview_cache.get(cache_key)

        if cached is not None and cached[0] == mtime:
            return cached[1]

        source = QtGui.QPixmap(path)

        if source.isNull():
            return None

        size = 112

        canvas = QtGui.QPixmap(size, size)
        canvas.fill(QtGui.QColor(30, 30, 30))

        scaled = source.scaled(
            size,
            size,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

        painter = QtGui.QPainter(canvas)

        try:
            offset_x = (size - scaled.width()) // 2
            offset_y = (size - scaled.height()) // 2

            painter.drawPixmap(offset_x, offset_y, scaled)

            if not available:
                painter.fillRect(
                    canvas.rect(),
                    QtGui.QColor(0, 0, 0, 145),
                )

                font = QtGui.QFont()
                font.setBold(True)
                font.setPixelSize(12)

                painter.setFont(font)
                painter.setPen(QtGui.QColor(245, 245, 245))

                painter.drawText(
                    canvas.rect(),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    "MISSING",
                )

        finally:
            painter.end()

        icon = QtGui.QIcon(canvas)
        self._preview_cache[cache_key] = (mtime, icon)

        return icon

    def create_type_thumbnail(
        self,
        resource_type: str,
        available: bool = True,
    ) -> QtGui.QIcon:
        size = 112

        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(45, 45, 45))

        painter = QtGui.QPainter(pixmap)

        try:
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.Antialiasing,
                True,
            )

            rect = QtCore.QRectF(6, 6, size - 12, size - 12)

            gradient = QtGui.QLinearGradient(
                rect.topLeft(),
                rect.bottomRight(),
            )

            type_lower = resource_type.lower()

            if "normal" in type_lower:
                gradient.setColorAt(
                    0.0,
                    QtGui.QColor(105, 88, 205),
                )
                gradient.setColorAt(
                    1.0,
                    QtGui.QColor(80, 130, 210),
                )
                short_name = "N"

            elif "ambient" in type_lower:
                gradient.setColorAt(
                    0.0,
                    QtGui.QColor(220, 220, 220),
                )
                gradient.setColorAt(
                    1.0,
                    QtGui.QColor(65, 65, 65),
                )
                short_name = "AO"

            elif "curvature" in type_lower:
                gradient.setColorAt(
                    0.0,
                    QtGui.QColor(210, 210, 210),
                )
                gradient.setColorAt(
                    1.0,
                    QtGui.QColor(90, 90, 90),
                )
                short_name = "C"

            elif "position" in type_lower:
                gradient.setColorAt(
                    0.0,
                    QtGui.QColor(180, 80, 80),
                )
                gradient.setColorAt(
                    1.0,
                    QtGui.QColor(70, 140, 105),
                )
                short_name = "P"

            elif "thickness" in type_lower:
                gradient.setColorAt(
                    0.0,
                    QtGui.QColor(225, 135, 60),
                )
                gradient.setColorAt(
                    1.0,
                    QtGui.QColor(90, 50, 30),
                )
                short_name = "T"

            else:
                gradient.setColorAt(
                    0.0,
                    QtGui.QColor(95, 110, 125),
                )
                gradient.setColorAt(
                    1.0,
                    QtGui.QColor(45, 55, 65),
                )
                short_name = "TEX"

            painter.setBrush(QtGui.QBrush(gradient))
            painter.setPen(
                QtGui.QPen(QtGui.QColor(85, 85, 85), 1)
            )
            painter.drawRoundedRect(rect, 5, 5)

            font = QtGui.QFont()
            font.setBold(True)
            font.setPixelSize(28)

            painter.setFont(font)
            painter.setPen(QtGui.QColor(245, 245, 245))

            painter.drawText(
                rect,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                short_name,
            )

            if not available:
                painter.fillRect(
                    pixmap.rect(),
                    QtGui.QColor(0, 0, 0, 145),
                )

                font.setPixelSize(12)
                painter.setFont(font)

                painter.drawText(
                    pixmap.rect(),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    "MISSING",
                )

        finally:
            painter.end()

        return QtGui.QIcon(pixmap)

    # ------------------------------------------------------------------
    # Drag and drop to Painter Layers
    # ------------------------------------------------------------------

    @staticmethod
    def is_layers_widget(widget: QtWidgets.QWidget) -> bool:
        """Return True when the drop target belongs to Painter's Layers dock."""
        current = widget

        while current is not None:
            try:
                class_name = current.metaObject().className()
            except Exception:
                class_name = type(current).__name__

            try:
                object_name = current.objectName()
            except Exception:
                object_name = ""

            try:
                title = current.windowTitle()
            except Exception:
                title = ""

            combined = (
                str(class_name)
                + " "
                + str(object_name)
                + " "
                + str(title)
            ).lower()

            if (
                "layersstackview" in combined
                or object_name == "LayersStackView"
                or title.strip().lower() == "layers"
            ):
                return True

            try:
                current = current.parentWidget()
            except Exception:
                break

        return False

    @staticmethod
    def widget_identity_text(widget: QtWidgets.QWidget) -> str:
        parts = []
        current = widget

        while current is not None:
            try:
                parts.append(current.metaObject().className())
            except Exception:
                parts.append(type(current).__name__)

            try:
                parts.append(current.objectName())
            except Exception:
                pass

            try:
                parts.append(current.windowTitle())
            except Exception:
                pass

            try:
                current = current.parentWidget()
            except Exception:
                break

        return " ".join(str(part) for part in parts).lower()

    @classmethod
    def is_properties_fill_widget(
        cls,
        widget: QtWidgets.QWidget,
    ) -> bool:
        identity = cls.widget_identity_text(widget)

        return (
            "properties - fill" in identity
            or "properties-fill" in identity
            or "properties fill" in identity
            or "layerinstanceview" in identity
            or "filllayer" in identity
            or "properties" in identity
            and (
                "material" in identity
                or "projection" in identity
                or "uv transformations" in identity
            )
        )

    @classmethod
    def is_texture_set_settings_widget(
        cls,
        widget: QtWidgets.QWidget,
    ) -> bool:
        identity = cls.widget_identity_text(widget)

        return (
            "texture set settings" in identity
            or "texture-set settings" in identity
            or "texturesetsettings" in identity
            or "baker map definition" in identity
            or "bakermapdefinitionview" in identity
            or "mesh maps" in identity
            or "select normal map" in identity
            or "select ambient occlusion map" in identity
        )

    @staticmethod
    def normalize_enum_key(value: str) -> str:
        return "".join(
            character
            for character in str(value).lower()
            if character.isalnum()
        )

    def available_layer_channels(self) -> list[tuple[str, Any]]:
        """Return only channels valid for the active Texture Set stack."""
        preferred = (
            ("Base Color", ("BaseColor", "Base_Color", "basecolor")),
            ("Roughness", ("Roughness", "roughness")),
            ("Metallic", ("Metallic", "metalness", "metallic")),
            ("Normal", ("Normal", "normal")),
            ("Height", ("Height", "height")),
            ("Opacity", ("Opacity", "opacity")),
            ("Emissive", ("Emissive", "emissive")),
            (
                "Ambient Occlusion",
                ("AmbientOcclusion", "Ambient_Occlusion", "AO"),
            ),
        )

        members = {
            self.normalize_enum_key(name): getattr(
                layerstack.ChannelType,
                name,
            )
            for name in dir(layerstack.ChannelType)
            if not name.startswith("_")
        }

        active_stack = substance_painter.textureset.get_active_stack()

        if active_stack is None:
            return []

        result = []

        for label, candidate_names in preferred:
            channel_value = None

            for candidate_name in candidate_names:
                channel_value = members.get(
                    self.normalize_enum_key(candidate_name)
                )

                if channel_value is not None:
                    break

            if channel_value is None:
                continue

            # Painter exposes enum entries such as AO even when that channel
            # does not exist in the current Texture Set. Using it then raises:
            # "Channel ... isn't valid in this context".
            try:
                if not active_stack.has_channel(channel_value):
                    continue
            except Exception:
                # Fallback for builds where has_channel expects the textureset
                # enum rather than layerstack.ChannelType.
                try:
                    textureset_member = None

                    for enum_name in dir(
                        substance_painter.textureset.ChannelType
                    ):
                        if enum_name.startswith("_"):
                            continue

                        if (
                            self.normalize_enum_key(enum_name)
                            == self.normalize_enum_key(
                                getattr(
                                    channel_value,
                                    "name",
                                    str(channel_value),
                                )
                            )
                        ):
                            textureset_member = getattr(
                                substance_painter.textureset.ChannelType,
                                enum_name,
                            )
                            break

                    if (
                        textureset_member is None
                        or not active_stack.has_channel(
                            textureset_member
                        )
                    ):
                        continue
                except Exception:
                    # Core channels are generally safe. AO is specifically a
                    # Mesh Map slot and normally not a Fill Layer channel.
                    if label == "Ambient Occlusion":
                        continue

            result.append(
                (
                    label,
                    channel_value,
                )
            )

        return result

    def infer_channel_label(self, record: dict[str, Any]) -> str:
        """Infer the most likely Fill Layer channel from type and file name."""
        text = (
            str(record.get("type", ""))
            + " "
            + str(record.get("alias", ""))
            + " "
            + str(record.get("original_name", ""))
            + " "
            + str(record.get("exported_file_name", ""))
        ).lower()

        rules = (
            ("Ambient Occlusion", ("ambient occlusion", "_ao", " ao")),
            ("Normal", ("normal", "_n")),
            ("Roughness", ("roughness", "_rough", "_rgh")),
            ("Metallic", ("metallic", "metalness", "_metal")),
            ("Height", ("height", "displacement", "_height")),
            ("Opacity", ("opacity", "alpha", "_opacity")),
            ("Emissive", ("emissive", "emission", "_emissive")),
            ("Base Color", ("base color", "basecolor", "albedo", "diffuse")),
        )

        for label, tokens in rules:
            if any(token in text for token in tokens):
                return label

        return "Base Color"

    def choose_drop_channel(
        self,
        record: dict[str, Any],
        global_position: QtCore.QPoint,
    ):
        channels = self.available_layer_channels()

        if not channels:
            raise RuntimeError(
                "Painter exposed no supported layer channels."
            )

        inferred_label = self.infer_channel_label(record)

        menu = QtWidgets.QMenu(self)
        menu.setTitle("Assign texture to channel")

        actions = {}

        for label, channel in channels:
            action_text = label

            if label == inferred_label:
                action_text += "  (Auto)"

            action = menu.addAction(action_text)
            actions[action] = (label, channel)

        selected_action = menu.exec(global_position)

        if selected_action is None:
            return None

        return actions[selected_action]

    def register_hidden_import(
        self,
        resource_id,
    ):
        """Hide a project resource imported only for layer assignment."""
        if not isinstance(
            resource_id,
            substance_painter.resource.ResourceID,
        ):
            return

        hidden_urls = set(
            self._data.setdefault(
                "hidden_resource_urls",
                [],
            )
        )
        hidden_urls.add(
            resource_id.url()
        )
        self._data["hidden_resource_urls"] = sorted(
            hidden_urls
        )

        # Remove an already-created duplicate tile immediately.
        self._data.setdefault(
            "resources",
            {},
        ).pop(
            resource_id.url(),
            None,
        )

        self.save_data()

    def import_texture_resource(self, file_path: str):
        """Import a bitmap into the current Painter project.

        Painter versions differ slightly in the accepted signature, so the
        function tries the supported variants.
        """
        importer = substance_painter.resource.import_project_resource
        usage_value = None

        for name in dir(substance_painter.resource.Usage):
            if name.startswith("_"):
                continue

            if self.normalize_enum_key(name) == "texture":
                usage_value = getattr(
                    substance_painter.resource.Usage,
                    name,
                )
                break

        attempts = []

        if usage_value is not None:
            attempts.extend(
                [
                    (file_path, usage_value),
                    (file_path, usage_value, None),
                ]
            )

        attempts.append((file_path,))

        errors = []

        for arguments in attempts:
            try:
                result = importer(*arguments)

                if result is None:
                    continue

                if isinstance(
                    result,
                    substance_painter.resource.ResourceID,
                ):
                    self.register_hidden_import(result)
                    return result

                identifier = getattr(result, "identifier", None)

                if callable(identifier):
                    resource_id = identifier()

                    if isinstance(
                        resource_id,
                        substance_painter.resource.ResourceID,
                    ):
                        self.register_hidden_import(
                            resource_id
                        )
                        return resource_id

                if isinstance(result, (list, tuple)) and result:
                    candidate = result[0]

                    if isinstance(
                        candidate,
                        substance_painter.resource.ResourceID,
                    ):
                        self.register_hidden_import(
                            candidate
                        )
                        return candidate

                    identifier = getattr(
                        candidate,
                        "identifier",
                        None,
                    )

                    if callable(identifier):
                        resource_id = identifier()

                        if isinstance(
                            resource_id,
                            substance_painter.resource.ResourceID,
                        ):
                            self.register_hidden_import(
                                resource_id
                            )
                            return resource_id

                errors.append(
                    "Import returned unsupported type: "
                    + type(result).__name__
                )

            except Exception as error:
                errors.append(str(error))

        raise RuntimeError(
            "Could not import the texture into the Painter project:\n"
            + "\n".join(errors)
        )

    @staticmethod
    def root_insert_position():
        active_stack = substance_painter.textureset.get_active_stack()

        if active_stack is None:
            raise RuntimeError(
                "No active Texture Set stack."
            )

        return layerstack.InsertPosition.from_textureset_stack(
            active_stack
        )

    def create_or_get_target_fill(self, layer_name: str):
        """Use the selected Fill Layer, otherwise create a new one."""
        active_stack = substance_painter.textureset.get_active_stack()

        if active_stack is None:
            raise RuntimeError(
                "No active Texture Set stack."
            )

        try:
            selected_nodes = layerstack.get_selected_nodes(
                active_stack
            )
        except TypeError:
            selected_nodes = layerstack.get_selected_nodes()

        if len(selected_nodes) == 1:
            node = selected_nodes[0]

            if isinstance(node, layerstack.FillLayerNode):
                return node, False

        fill = layerstack.insert_fill(
            self.root_insert_position()
        )
        fill.set_name(layer_name)

        try:
            layerstack.set_selected_nodes([fill])
        except Exception:
            pass

        return fill, True

    @staticmethod
    def set_only_active_channel(fill, channel):
        try:
            fill.active_channels = {channel}
            return
        except Exception:
            pass

        try:
            fill.active_channels = [channel]
        except Exception:
            pass

    def resolve_assignment_resource(
        self,
        file_path: str,
        source_url: Optional[str] = None,
        preferred_urls: Optional[list[str]] = None,
    ):
        """Reuse a live Painter resource before importing the disk file."""
        candidate_urls = []

        if source_url:
            candidate_urls.append(
                str(
                    source_url
                )
            )

        for value in (
            preferred_urls
            or []
        ):
            value = str(
                value
            )

            if (
                value
                and value
                not in candidate_urls
            ):
                candidate_urls.append(
                    value
                )

        try:
            active_resources = {
                resource_id.url(): resource_id
                for resource_id
                in substance_painter.resource.list_project_resources()
                if str(
                    resource_id.context
                ).startswith(
                    "project"
                )
            }

            for candidate_url in candidate_urls:
                resource_id = active_resources.get(
                    candidate_url
                )

                if resource_id is not None:
                    return (
                        resource_id,
                        False,
                    )

        except Exception:
            traceback.print_exc()

        return (
            self.import_texture_resource(
                file_path
            ),
            True,
        )

    def assign_file_to_layer_channel(
        self,
        file_path: str,
        layer_name: str,
        channel,
        source_url: Optional[str] = None,
    ):
        active_stack = substance_painter.textureset.get_active_stack()

        if active_stack is None:
            raise RuntimeError(
                "No active Texture Set stack."
            )

        try:
            channel_is_valid = active_stack.has_channel(
                channel
            )
        except Exception:
            channel_is_valid = True

        if not channel_is_valid:
            raise RuntimeError(
                "The selected channel does not exist in the active "
                "Texture Set. Add the channel in Texture Set Settings "
                "or choose another channel."
            )

        resource_id, was_imported = (
            self.resolve_assignment_resource(
                file_path,
                source_url,
            )
        )

        if source_url:
            record = self._data.setdefault(
                "resources",
                {},
            ).get(source_url)

            if record is not None:
                painter_urls = list(
                    record.get(
                        "painter_resource_urls",
                        [],
                    )
                )
                resource_url = resource_id.url()

                if resource_url not in painter_urls:
                    painter_urls.append(
                        resource_url
                    )

                record[
                    "painter_resource_urls"
                ] = painter_urls
                self.save_data()

        fill, was_created = self.create_or_get_target_fill(
            layer_name
        )

        self.set_only_active_channel(
            fill,
            channel,
        )

        fill.set_source(
            channel,
            resource_id,
        )

        return (
            fill,
            resource_id,
            was_created,
            was_imported,
        )

    def handle_drop_to_layers(
        self,
        items: list[QtWidgets.QListWidgetItem],
        global_position: QtCore.QPoint,
    ):
        """Assign dragged texture files to a chosen Fill Layer channel."""
        if not substance_painter.project.is_open():
            self.status_label.setText(
                "Open a Painter project first."
            )
            return

        if not items:
            return

        # One channel chooser is shown for the first item. Multiple selected
        # textures are then each placed into their own Fill Layer.
        first_url = items[0].data(ROLE_RESOURCE_URL)
        first_record = self._data.get("resources", {}).get(
            first_url,
            {},
        )

        choice = self.choose_drop_channel(
            first_record,
            global_position,
        )

        if choice is None:
            self.status_label.setText(
                "Texture assignment cancelled."
            )
            return

        channel_label, channel = choice
        assigned = 0

        try:
            for item in items:
                file_path = item.data(ROLE_DRAG_PATH)

                if not file_path or not os.path.isfile(str(file_path)):
                    continue

                url = item.data(ROLE_RESOURCE_URL)
                record = self._data.get("resources", {}).get(
                    url,
                    {},
                )

                layer_name = record.get(
                    "alias",
                    os.path.splitext(
                        os.path.basename(str(file_path))
                    )[0],
                )

                self.assign_file_to_layer_channel(
                    os.path.normpath(str(file_path)),
                    layer_name,
                    channel,
                    source_url=url,
                )

                assigned += 1

            self.status_label.setText(
                f"Assigned {assigned} texture(s) to {channel_label} "
                "without re-importing current bake resources."
            )

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not assign the texture. See Python Console."
            )

    def handle_drop_to_properties(
        self,
        items: list[QtWidgets.QListWidgetItem],
        global_position: QtCore.QPoint,
    ):
        print("[BakeManager] Drop target: Properties - Fill")
        """Assign a texture to the currently selected Fill Layer.

        Dropping on Properties - Fill never creates a layer silently unless
        there is no selected Fill Layer. The same channel chooser is used as
        for the Layers panel.
        """
        if not items:
            return

        first_url = items[0].data(ROLE_RESOURCE_URL)
        first_record = self._data.get("resources", {}).get(
            first_url,
            {},
        )

        choice = self.choose_drop_channel(
            first_record,
            global_position,
        )

        if choice is None:
            self.status_label.setText(
                "Texture assignment cancelled."
            )
            return

        channel_label, channel = choice
        assigned = 0

        try:
            for item in items:
                file_path = item.data(ROLE_DRAG_PATH)

                if not file_path or not os.path.isfile(str(file_path)):
                    continue

                url = item.data(ROLE_RESOURCE_URL)
                record = self._data.get("resources", {}).get(
                    url,
                    {},
                )

                layer_name = record.get(
                    "alias",
                    os.path.splitext(
                        os.path.basename(str(file_path))
                    )[0],
                )

                self.assign_file_to_layer_channel(
                    os.path.normpath(str(file_path)),
                    layer_name,
                    channel,
                    source_url=url,
                )
                assigned += 1

            self.status_label.setText(
                f"Assigned {assigned} texture(s) to "
                f"{channel_label} in Properties - Fill."
            )

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not assign the texture in Properties. "
                "See Python Console."
            )

    def available_mesh_map_usages(self) -> list[tuple[str, Any]]:
        """Return mesh-map slots exposed by this Painter build."""
        usage_enum = substance_painter.textureset.MeshMapUsage
        members = getattr(usage_enum, "__members__", {})

        preferred_labels = {
            "ao": "Ambient Occlusion",
            "ambientocclusion": "Ambient Occlusion",
            "normal": "Normal",
            "worldspacenormal": "World Space Normal",
            "id": "ID",
            "curvature": "Curvature",
            "position": "Position",
            "thickness": "Thickness",
            "height": "Height",
            "opacity": "Opacity",
            "bentnormals": "Bent Normals",
        }

        result = []

        if members:
            iterable = members.items()
        else:
            iterable = (
                (name, getattr(usage_enum, name))
                for name in dir(usage_enum)
                if not name.startswith("_")
            )

        for name, value in iterable:
            normalized = self.normalize_enum_key(name)
            label = preferred_labels.get(
                normalized,
                str(name).replace("_", " "),
            )
            result.append((label, value))

        result.sort(key=lambda pair: pair[0].lower())
        return result

    def infer_mesh_map_label(
        self,
        record: dict[str, Any],
    ) -> str:
        text = (
            str(record.get("type", ""))
            + " "
            + str(record.get("alias", ""))
            + " "
            + str(record.get("original_name", ""))
            + " "
            + str(record.get("exported_file_name", ""))
        ).lower()

        rules = (
            ("Ambient Occlusion", ("ambient occlusion", "_ao", " ao")),
            ("World Space Normal", ("world space normal", "worldspacenormal")),
            ("Normal", ("normal", "_n")),
            ("Curvature", ("curvature",)),
            ("Position", ("position",)),
            ("Thickness", ("thickness",)),
            ("ID", ("id map", "_id")),
            ("Height", ("height", "displacement")),
            ("Opacity", ("opacity", "alpha")),
            ("Bent Normals", ("bent normal", "bentnormal")),
        )

        for label, tokens in rules:
            if any(token in text for token in tokens):
                return label

        return "Normal"

    def choose_mesh_map_usage(
        self,
        record: dict[str, Any],
        global_position: QtCore.QPoint,
    ):
        usages = self.available_mesh_map_usages()

        if not usages:
            raise RuntimeError(
                "Painter exposed no MeshMapUsage values."
            )

        inferred_label = self.infer_mesh_map_label(record)
        menu = QtWidgets.QMenu(self)
        menu.setTitle("Assign as Mesh Map")

        actions = {}

        for label, usage in usages:
            action_text = label

            if label == inferred_label:
                action_text += "  (Auto)"

            action = menu.addAction(action_text)
            actions[action] = (label, usage)

        chosen = menu.exec(global_position)

        if chosen is None:
            return None

        return actions[chosen]

    def active_texture_set_object(self):
        """Resolve the TextureSet that owns the active Stack.

        In Painter 11.1.3 Stack.material is not a reliable TextureSet object,
        so match the active stack against every TextureSet and its stacks.
        """
        active_stack = substance_painter.textureset.get_active_stack()

        if active_stack is None:
            raise RuntimeError(
                "No active Texture Set stack."
            )

        texture_sets = list(
            substance_painter.textureset.all_texture_sets()
        )

        if not texture_sets:
            raise RuntimeError(
                "The project contains no Texture Sets."
            )

        def member_value(obj, name):
            member = getattr(obj, name, None)

            if callable(member):
                try:
                    return member()
                except Exception:
                    return None

            return member

        def stack_key(stack):
            if stack is None:
                return None

            stack_id = member_value(stack, "stack_id")

            if stack_id is not None:
                return ("id", str(stack_id))

            stack_name = member_value(stack, "name")

            if stack_name is not None:
                return ("name", str(stack_name))

            return ("repr", str(stack))

        active_key = stack_key(active_stack)

        for texture_set in texture_sets:
            candidate_stacks = []

            for member_name in (
                "all_stacks",
                "stacks",
            ):
                stacks = member_value(
                    texture_set,
                    member_name,
                )

                if stacks is None:
                    continue

                try:
                    candidate_stacks.extend(
                        list(stacks)
                    )
                except TypeError:
                    pass

            for candidate_stack in candidate_stacks:
                if candidate_stack is active_stack:
                    return texture_set

                if stack_key(candidate_stack) == active_key:
                    return texture_set

        # In a project with one Texture Set there is no ambiguity.
        if len(texture_sets) == 1:
            return texture_sets[0]

        # Last fallback: active stack name often equals the Texture Set name.
        active_name = member_value(
            active_stack,
            "name",
        )

        if active_name is not None:
            active_name = str(active_name)

            for texture_set in texture_sets:
                texture_set_name = member_value(
                    texture_set,
                    "name",
                )

                if (
                    texture_set_name is not None
                    and str(texture_set_name) == active_name
                ):
                    return texture_set

        available_names = []

        for texture_set in texture_sets:
            name = member_value(
                texture_set,
                "name",
            )
            available_names.append(
                str(name if name is not None else texture_set)
            )

        raise RuntimeError(
            "Could not determine the active Texture Set. "
            f"Active stack: {active_stack}. "
            f"Available Texture Sets: {available_names}"
        )

    def set_texture_set_mesh_map(
        self,
        usage,
        resource_id,
    ):
        if not isinstance(
            resource_id,
            substance_painter.resource.ResourceID,
        ):
            raise TypeError(
                "Mesh Map assignment requires ResourceID, got "
                + type(resource_id).__name__
            )

        texture_set = self.active_texture_set_object()
        setter = getattr(
            texture_set,
            "set_mesh_map_resource",
            None,
        )

        if setter is None:
            raise RuntimeError(
                "TextureSet.set_mesh_map_resource is unavailable."
            )

        setter(usage, resource_id)

    def handle_drop_to_texture_set_settings(
        self,
        items: list[QtWidgets.QListWidgetItem],
        global_position: QtCore.QPoint,
    ):
        print("[BakeManager] Drop target: Texture Set Settings")
        """Assign the dropped texture to a Mesh Maps slot."""
        if not substance_painter.project.is_open():
            self.status_label.setText(
                "Open a Painter project first."
            )
            return

        if not items:
            return

        item = items[0]
        url = item.data(ROLE_RESOURCE_URL)
        record = self._data.get("resources", {}).get(
            url,
            {},
        )

        choice = self.choose_mesh_map_usage(
            record,
            global_position,
        )

        if choice is None:
            self.status_label.setText(
                "Mesh Map assignment cancelled."
            )
            return

        label, usage = choice
        file_path = item.data(ROLE_DRAG_PATH)

        if not file_path or not os.path.isfile(str(file_path)):
            self.status_label.setText(
                "The texture file is missing on disk."
            )
            return

        try:
            resource_id, _was_imported = (
                self.resolve_assignment_resource(
                    os.path.normpath(str(file_path)),
                    source_url=url,
                )
            )

            self.set_texture_set_mesh_map(
                usage,
                resource_id,
            )

            self.status_label.setText(
                f"Assigned {item.text()} as {label} Mesh Map."
            )

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not assign the Mesh Map. "
                "See Python Console."
            )

    # ------------------------------------------------------------------
    # Marmoset Toolbag 5 bridge
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_external_file_path(
        value: Any,
    ) -> str:
        if value is None:
            return ""

        path = str(value).strip().strip('"')

        if path.lower().startswith("file:///"):
            path = QtCore.QUrl(path).toLocalFile()

        return os.path.normpath(path)

    def marmoset_bridge_settings(self) -> dict[str, Any]:
        return self._data.setdefault(
            "marmoset_bridge",
            {
                "toolbag_exe": "",
                "high_poly_paths": [],
            },
        )

    def toolbag_global_settings(self):
        """Store one Toolbag path for all Painter projects."""
        return QtCore.QSettings(
            "CustomAssetManager",
            "MarmosetBridge",
        )

    def remember_toolbag_executable(
        self,
        path: str,
    ) -> str:
        path = os.path.normpath(
            str(path)
        )

        global_settings = self.toolbag_global_settings()
        global_settings.setValue(
            "toolbag_exe",
            path,
        )
        global_settings.sync()

        self.marmoset_bridge_settings()[
            "toolbag_exe"
        ] = path
        self.save_data()

        return path

    def detect_toolbag_executable(self) -> Optional[str]:
        global_settings = self.toolbag_global_settings()

        globally_stored = self.normalize_external_file_path(
            global_settings.value(
                "toolbag_exe",
                "",
            )
        )

        if (
            globally_stored
            and os.path.isfile(globally_stored)
        ):
            return globally_stored

        project_stored = self.normalize_external_file_path(
            self.marmoset_bridge_settings().get(
                "toolbag_exe",
                "",
            )
        )

        if (
            project_stored
            and os.path.isfile(project_stored)
        ):
            return self.remember_toolbag_executable(
                project_stored
            )

        default_directory = (
            r"C:\Program Files\Marmoset\Toolbag 5"
        )

        preferred_names = (
            "Toolbag.exe",
            "toolbag.exe",
            "Marmoset Toolbag.exe",
            "MarmosetToolbag.exe",
        )

        candidates = [
            os.path.join(
                default_directory,
                executable_name,
            )
            for executable_name in preferred_names
        ]

        candidates.extend(
            sorted(
                glob.glob(
                    os.path.join(
                        default_directory,
                        "*.exe",
                    )
                )
            )
        )

        # Compatibility with an alternative installer folder name.
        candidates.extend(
            sorted(
                glob.glob(
                    r"C:\Program Files\Marmoset Toolbag 5*\*.exe"
                )
            )
        )

        seen = set()

        for candidate in candidates:
            normalized = os.path.normcase(
                os.path.abspath(candidate)
            )

            if normalized in seen:
                continue

            seen.add(normalized)

            if not os.path.isfile(candidate):
                continue

            executable_name = os.path.basename(
                candidate
            ).lower()

            if (
                "toolbag" not in executable_name
                and "marmoset" not in executable_name
            ):
                continue

            return self.remember_toolbag_executable(
                candidate
            )

        return None

    def choose_toolbag_executable(self) -> Optional[str]:
        current = self.detect_toolbag_executable() or ""
        default_directory = (
            r"C:\Program Files\Marmoset\Toolbag 5"
        )

        start_directory = (
            os.path.dirname(current)
            if current
            else default_directory
        )

        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Toolbag 5 was not found — choose its executable",
            start_directory,
            "Applications (*.exe);;All files (*.*)",
        )

        if not path:
            return None

        path = self.remember_toolbag_executable(
            path
        )

        self.status_label.setText(
            "Toolbag executable saved globally."
        )

        return path

    def current_low_poly_path(self) -> Optional[str]:
        getter = getattr(
            substance_painter.project,
            "last_imported_mesh_path",
            None,
        )

        if not callable(getter):
            return None

        try:
            path = self.normalize_external_file_path(
                getter()
            )
        except Exception:
            traceback.print_exc()
            return None

        if path and os.path.isfile(path):
            return path

        return None

    @classmethod
    def collect_mesh_paths_from_value(
        cls,
        value: Any,
        parent_key: str = "",
        result: Optional[list[tuple[int, str]]] = None,
    ) -> list[tuple[int, str]]:
        if result is None:
            result = []

        key_text = str(parent_key).lower()

        if isinstance(value, dict):
            for key, child_value in value.items():
                cls.collect_mesh_paths_from_value(
                    child_value,
                    str(key),
                    result,
                )

            return result

        if isinstance(value, (list, tuple, set)):
            for child_value in value:
                cls.collect_mesh_paths_from_value(
                    child_value,
                    parent_key,
                    result,
                )

            return result

        if not isinstance(value, str):
            return result

        path = cls.normalize_external_file_path(value)
        extension = os.path.splitext(path)[1].lower()

        mesh_extensions = {
            ".fbx",
            ".obj",
            ".abc",
            ".dae",
            ".3ds",
            ".ply",
            ".stl",
            ".usd",
            ".usda",
            ".usdc",
            ".gltf",
            ".glb",
        }

        if extension not in mesh_extensions or not os.path.isfile(path):
            return result

        score = 0
        file_name = os.path.basename(path).lower()

        if any(
            token in key_text
            for token in (
                "high",
                "highdefinition",
                "high_definition",
                "hipoly",
                "highpoly",
            )
        ):
            score += 100

        if any(
            token in file_name
            for token in (
                "_high",
                "-high",
                " high",
                "highpoly",
                "high_poly",
            )
        ):
            score += 30

        if "cage" in key_text or "cage" in file_name:
            score -= 200

        if any(
            token in key_text
            for token in (
                "low",
                "lowpoly",
                "low_poly",
            )
        ):
            score -= 100

        result.append(
            (
                score,
                os.path.normpath(path),
            )
        )
        return result

    def painter_high_poly_paths(self) -> list[str]:
        """Read high-poly paths from Painter's current baking parameters."""
        payloads = []

        try:
            payloads.append(
                spjs.evaluate(
                    "alg.baking.commonBakingParameters()"
                )
            )
        except Exception:
            pass

        try:
            texture_sets = list(
                substance_painter.textureset.all_texture_sets()
            )
        except Exception:
            texture_sets = []

        for texture_set in texture_sets:
            try:
                texture_set_name = texture_set.name()
                payloads.append(
                    spjs.evaluate(
                        "alg.baking.textureSetBakingParameters("
                        + json.dumps(texture_set_name)
                        + ")"
                    )
                )
            except Exception:
                continue

        low_path = self.current_low_poly_path()
        scored_paths = []

        for payload in payloads:
            scored_paths.extend(
                self.collect_mesh_paths_from_value(
                    payload
                )
            )

        unique = {}

        for score, path in scored_paths:
            normalized = os.path.normcase(
                os.path.abspath(path)
            )

            if (
                low_path
                and normalized
                == os.path.normcase(
                    os.path.abspath(low_path)
                )
            ):
                continue

            previous = unique.get(normalized)

            if previous is None or score > previous[0]:
                unique[normalized] = (
                    score,
                    path,
                )

        strong_matches = [
            path
            for score, path in unique.values()
            if score > 0
        ]

        strong_matches.sort(
            key=lambda path: path.lower()
        )

        if strong_matches:
            settings = self.marmoset_bridge_settings()
            settings["high_poly_paths"] = strong_matches
            self.save_data()
            return strong_matches

        stored_paths = []

        for path in self.marmoset_bridge_settings().get(
            "high_poly_paths",
            [],
        ):
            normalized = self.normalize_external_file_path(path)

            if normalized and os.path.isfile(normalized):
                stored_paths.append(normalized)

        return stored_paths

    def choose_high_poly_paths(self) -> list[str]:
        low_path = self.current_low_poly_path()
        start_directory = (
            os.path.dirname(low_path)
            if low_path
            else ""
        )

        paths, _selected_filter = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Choose high-poly mesh file(s)",
            start_directory,
            (
                "3D meshes (*.fbx *.obj *.abc *.dae *.3ds *.ply "
                "*.stl *.usd *.usda *.usdc *.gltf *.glb);;"
                "All files (*.*)"
            ),
        )

        normalized_paths = [
            os.path.normpath(path)
            for path in paths
            if os.path.isfile(path)
        ]

        if normalized_paths:
            self.marmoset_bridge_settings()[
                "high_poly_paths"
            ] = normalized_paths
            self.save_data()

        return normalized_paths

    def marmoset_bridge_directory(self) -> Optional[str]:
        cache_dir = self.preview_cache_dir()

        if not cache_dir:
            return None

        return os.path.join(
            cache_dir,
            "_MarmosetBridge",
        )

    def write_marmoset_worker(self) -> Optional[str]:
        bridge_directory = self.marmoset_bridge_directory()

        if not bridge_directory:
            return None

        os.makedirs(
            bridge_directory,
            exist_ok=True,
        )

        worker_path = os.path.join(
            bridge_directory,
            "marmoset_painter_bake_bridge.py",
        )

        worker_source = 'import json\nimport os\nimport re\nimport shutil\nimport sys\nimport time\nimport traceback\n\nimport mset\n\n\nJOB = {}\nJOB_PATH = ""\nBAKER = None\nBRIDGE_WINDOW = None\nSTATUS_LABEL = None\nPENDING_BAKE = None\nROOT_CLEANUP_UNTIL = 0.0\n\n# Raw files that may briefly appear while Toolbag is baking.\nRAW_IMAGE_EXTENSIONS = (\n    ".png",\n    ".tga",\n    ".jpg",\n    ".jpeg",\n    ".psd",\n    ".tif",\n    ".tiff",\n)\n\nMAP_INFO = (\n    ("bentnormal", "BN", "Bent Normals"),\n    ("worldspacenormal", "WSN", "World Space Normal"),\n    ("objectnormal", "WSN", "World Space Normal"),\n    ("ambientocclusion", "AO", "Ambient Occlusion"),\n    ("aobakermap", "AO", "Ambient Occlusion"),\n    ("curvature", "C", "Curvature"),\n    ("thickness", "T", "Thickness"),\n    ("position", "P", "Position"),\n    ("height", "H", "Height"),\n    ("materialid", "ID", "ID Map"),\n    ("objectid", "ID", "ID Map"),\n    ("groupid", "ID", "ID Map"),\n    ("opacity", "O", "Opacity"),\n    ("transparency", "O", "Opacity"),\n    ("normal", "N", "Normal"),\n)\n\n\ndef write_json_atomic(path, payload):\n    os.makedirs(os.path.dirname(path), exist_ok=True)\n    temporary_path = path + ".tmp"\n\n    with open(temporary_path, "w", encoding="utf-8") as stream:\n        json.dump(\n            payload,\n            stream,\n            ensure_ascii=False,\n            indent=4,\n        )\n\n    os.replace(temporary_path, path)\n\n\ndef write_status(state, message, **extra):\n    status_path = JOB.get("status_path", "")\n\n    if not status_path:\n        return\n\n    payload = {\n        "version": 3,\n        "state": state,\n        "message": message,\n        "updated_at": time.time(),\n    }\n    payload.update(extra)\n\n    try:\n        write_json_atomic(status_path, payload)\n    except Exception:\n        traceback.print_exc()\n\n\ndef set_status_text(message):\n    global STATUS_LABEL\n\n    if STATUS_LABEL is not None:\n        try:\n            STATUS_LABEL.text = message\n        except Exception:\n            pass\n\n    print("[PainterBridge] " + message)\n\n\ndef safe_name(value):\n    value = str(value or "Texture_Set").strip()\n\n    for character in \'<>:"/\\\\|?*\':\n        value = value.replace(character, "_")\n\n    value = value.rstrip(". ")\n\n    return value or "Texture_Set"\n\n\ndef normalized_token(value):\n    return re.sub(\n        r"[^a-z0-9]+",\n        "",\n        str(value).lower(),\n    )\n\n\ndef child_named(parent, wanted):\n    wanted = wanted.strip().lower()\n\n    try:\n        for child in parent.getChildren():\n            if str(child.name).strip().lower() == wanted:\n                return child\n    except Exception:\n        pass\n\n    try:\n        found = parent.findInChildren(wanted.capitalize())\n\n        if found is not None:\n            return found\n    except Exception:\n        pass\n\n    return None\n\n\ndef set_visibility_recursive(scene_object, visible):\n    try:\n        scene_object.visible = bool(visible)\n    except Exception:\n        pass\n\n    try:\n        children = list(scene_object.getChildren())\n    except Exception:\n        children = []\n\n    for child in children:\n        set_visibility_recursive(\n            child,\n            visible,\n        )\n\n\ndef object_uid(scene_object):\n    try:\n        return str(scene_object.uid)\n    except Exception:\n        return str(id(scene_object))\n\n\ndef import_under(path, parent):\n    """Import a model and parent every newly created root under a bake slot."""\n    before_objects = list(\n        mset.getAllObjects()\n    )\n    before_uids = {\n        object_uid(scene_object)\n        for scene_object in before_objects\n    }\n\n    imported = mset.importModel(path)\n\n    after_objects = list(\n        mset.getAllObjects()\n    )\n    new_objects = [\n        scene_object\n        for scene_object in after_objects\n        if object_uid(scene_object) not in before_uids\n    ]\n    new_uids = {\n        object_uid(scene_object)\n        for scene_object in new_objects\n    }\n\n    roots = []\n\n    if imported is not None:\n        roots.append(imported)\n\n    for scene_object in new_objects:\n        try:\n            object_parent = scene_object.parent\n        except Exception:\n            object_parent = None\n\n        if (\n            object_parent is None\n            or object_uid(object_parent) not in new_uids\n        ):\n            if scene_object not in roots:\n                roots.append(scene_object)\n\n    if not roots:\n        raise RuntimeError(\n            "Toolbag did not create scene objects for: " + path\n        )\n\n    imported_name = os.path.splitext(\n        os.path.basename(path)\n    )[0]\n\n    for index, root in enumerate(roots):\n        root.parent = parent\n\n        try:\n            root.visible = True\n        except Exception:\n            pass\n\n        try:\n            if len(roots) == 1:\n                root.name = imported_name\n            else:\n                root.name = (\n                    imported_name\n                    + "_"\n                    + str(index + 1)\n                )\n        except Exception:\n            pass\n\n    return roots\n\n\ndef direct_child_count(parent):\n    try:\n        return len(\n            list(parent.getChildren())\n        )\n    except Exception:\n        return 0\n\n\ndef map_code_and_label(map_object):\n    class_name = type(map_object).__name__.lower()\n    suffix = str(\n        getattr(map_object, "suffix", "")\n    ).lower()\n    identity = normalized_token(\n        class_name + " " + suffix\n    )\n\n    for token, code, label in MAP_INFO:\n        if token in identity:\n            return code, label\n\n    cleaned_suffix = re.sub(\n        r"[^A-Za-z0-9]+",\n        "",\n        str(getattr(map_object, "suffix", "")),\n    ).upper()\n\n    if cleaned_suffix:\n        return cleaned_suffix[:12], cleaned_suffix[:12]\n\n    fallback = re.sub(\n        r"bakermap$",\n        "",\n        class_name,\n    )\n    fallback = re.sub(\n        r"[^a-z0-9]+",\n        "",\n        fallback,\n    ).upper()\n\n    return fallback[:12] or "MAP", fallback[:12] or "Map"\n\n\ndef configure_enabled_maps():\n    configured = []\n\n    for map_object in BAKER.getAllMaps():\n        try:\n            enabled = bool(map_object.enabled)\n        except Exception:\n            enabled = True\n\n        if not enabled:\n            continue\n\n        code, label = map_code_and_label(map_object)\n\n        try:\n            map_object.suffix = "_" + code\n        except Exception:\n            traceback.print_exc()\n\n        configured.append(\n            {\n                "code": code,\n                "label": label,\n                "class_name": type(map_object).__name__,\n                "suffix": str(\n                    getattr(map_object, "suffix", "")\n                ),\n            }\n        )\n\n    return configured\n\n\ndef ensure_multiple_texture_sets():\n    """Keep Toolbag\'s Tile Mode set to Multiple Texture Sets."""\n    applied = False\n\n    try:\n        BAKER.multipleTextureSets = True\n        applied = bool(\n            BAKER.multipleTextureSets\n        )\n    except Exception:\n        pass\n\n    # Some Toolbag builds expose the same option as tileMode. Use it only\n    # when present, so older/newer API variants do not fail.\n    if hasattr(BAKER, "tileMode"):\n        for value in (\n            "Multiple Texture Sets",\n            "MultipleTextureSets",\n            "Multiple",\n        ):\n            try:\n                BAKER.tileMode = value\n                applied = True\n                break\n            except Exception:\n                continue\n\n    return applied\n\n\ndef force_png_output():\n    """Force separate PNG files across Toolbag API revisions."""\n    applied = []\n\n    # In Toolbag 5.02 the former outputSinglePsd member may be absent.\n    # An explicit .png output path is therefore the primary format signal.\n    base_name = safe_name(\n        JOB.get(\n            "output_base_name",\n            JOB.get(\n                "baker_name",\n                "Painter_Bake",\n            ),\n        )\n    )\n    output_path = os.path.join(\n        JOB["output_directory"],\n        base_name + ".png",\n    )\n    BAKER.outputPath = output_path\n    applied.append(\n        {\n            "member": "outputPath",\n            "value": output_path,\n        }\n    )\n\n    # Try format members exposed by newer Toolbag builds without depending\n    # on one exact API spelling.\n    member_names = (\n        "outputFormat",\n        "outputFileFormat",\n        "outputImageFormat",\n        "imageFormat",\n        "fileFormat",\n        "format",\n    )\n\n    for member_name in member_names:\n        if not hasattr(BAKER, member_name):\n            continue\n\n        for value in ("PNG", "png", ".png"):\n            try:\n                setattr(\n                    BAKER,\n                    member_name,\n                    value,\n                )\n                applied.append(\n                    {\n                        "member": member_name,\n                        "value": value,\n                    }\n                )\n                break\n            except Exception:\n                continue\n\n    # Request 16 bits per channel. Toolbag 5 builds have used several\n    # property names, so use the first compatible one.\n    bit_depth_members = (\n        "outputBits",\n        "outputBitDepth",\n        "outputBitsPerChannel",\n        "bitsPerChannel",\n        "bitDepth",\n    )\n\n    bit_depth_applied = False\n\n    for member_name in bit_depth_members:\n        if not hasattr(BAKER, member_name):\n            continue\n\n        for value in (\n            16,\n            "16",\n            "16 bit",\n            "16-bit",\n        ):\n            try:\n                setattr(\n                    BAKER,\n                    member_name,\n                    value,\n                )\n                applied.append(\n                    {\n                        "member": member_name,\n                        "value": value,\n                    }\n                )\n                bit_depth_applied = True\n                break\n            except Exception:\n                continue\n\n        if bit_depth_applied:\n            break\n\n    # Older versions expose this switch; newer versions simply omit it.\n    if hasattr(BAKER, "outputSinglePsd"):\n        try:\n            BAKER.outputSinglePsd = False\n            applied.append(\n                {\n                    "member": "outputSinglePsd",\n                    "value": False,\n                }\n            )\n        except Exception:\n            pass\n\n    return applied\n\n\ndef all_known_texture_sets():\n    result = []\n\n    for name in JOB.get(\n        "texture_set_names",\n        [],\n    ):\n        name = str(name).strip()\n\n        if (\n            name\n            and name not in result\n        ):\n            result.append(name)\n\n    return result\n\n\ndef choose_texture_set_for_file(\n    file_name,\n    texture_set_names,\n):\n    file_token = normalized_token(\n        os.path.splitext(file_name)[0]\n    )\n\n    matches = []\n\n    for name in texture_set_names:\n        token = normalized_token(name)\n\n        if token and token in file_token:\n            matches.append(\n                (\n                    len(token),\n                    name,\n                )\n            )\n\n    if matches:\n        matches.sort(reverse=True)\n        return matches[0][1]\n\n    if len(texture_set_names) == 1:\n        return texture_set_names[0]\n\n    return "Unmatched"\n\n\ndef infer_file_map_type(file_name):\n    stem = os.path.splitext(\n        file_name\n    )[0].lower()\n\n    # Long names must be checked before "normal".\n    patterns = (\n        (\n            (\n                "world_space_normal",\n                "worldspacenormal",\n                "object_space_normal",\n                "objectspacenormal",\n                "object_normal",\n                "_wsn",\n            ),\n            "WSN",\n            "World Space Normal",\n        ),\n        (\n            (\n                "bent_normals",\n                "bent_normal",\n                "bentnormals",\n                "bentnormal",\n                "_bn",\n            ),\n            "BN",\n            "Bent Normals",\n        ),\n        (\n            (\n                "ambient_occlusion",\n                "ambientocclusion",\n                "occlusion",\n                "_ao",\n            ),\n            "AO",\n            "Ambient Occlusion",\n        ),\n        (\n            (\n                "curvature",\n                "_curv",\n                "_c",\n            ),\n            "C",\n            "Curvature",\n        ),\n        (\n            (\n                "thickness",\n                "_thick",\n                "_t",\n            ),\n            "T",\n            "Thickness",\n        ),\n        (\n            (\n                "position",\n                "_pos",\n                "_p",\n            ),\n            "P",\n            "Position",\n        ),\n        (\n            (\n                "height",\n                "displacement",\n                "_h",\n            ),\n            "H",\n            "Height",\n        ),\n        (\n            (\n                "material_id",\n                "materialid",\n                "object_id",\n                "objectid",\n                "group_id",\n                "groupid",\n                "_id",\n            ),\n            "ID",\n            "ID Map",\n        ),\n        (\n            (\n                "opacity",\n                "transparency",\n                "_o",\n            ),\n            "O",\n            "Opacity",\n        ),\n        (\n            (\n                "normal",\n                "_n",\n            ),\n            "N",\n            "Normal",\n        ),\n    )\n\n    for tokens, code, label in patterns:\n        for token in tokens:\n            if token.startswith("_") and len(token) <= 3:\n                if re.search(\n                    re.escape(token)\n                    + r"(?:_\\d+)?$",\n                    stem,\n                ):\n                    return code, label\n            elif token in stem:\n                return code, label\n\n    return "MAP", "Texture"\n\n\ndef clear_raw_output_files():\n    output_directory = JOB["output_directory"]\n\n    if not os.path.isdir(output_directory):\n        return\n\n    for file_name in os.listdir(\n        output_directory\n    ):\n        path = os.path.join(\n            output_directory,\n            file_name,\n        )\n\n        if not os.path.isfile(path):\n            continue\n\n        extension = os.path.splitext(\n            file_name\n        )[1].lower()\n\n        if extension not in RAW_IMAGE_EXTENSIONS:\n            continue\n\n        try:\n            os.remove(path)\n        except OSError:\n            traceback.print_exc()\n\n\ndef collect_raw_output_files(recent_since=None):\n    output_directory = JOB["output_directory"]\n    result = []\n\n    if not os.path.isdir(output_directory):\n        return result\n\n    for root, _directories, file_names in os.walk(\n        output_directory\n    ):\n        # Ignore already organized per-set output from older bakes.\n        if os.path.normcase(root) != os.path.normcase(\n            output_directory\n        ):\n            continue\n\n        for file_name in file_names:\n            extension = os.path.splitext(\n                file_name\n            )[1].lower()\n\n            if extension not in RAW_IMAGE_EXTENSIONS:\n                continue\n\n            path = os.path.normpath(\n                os.path.join(root, file_name)\n            )\n\n            try:\n                modified = os.path.getmtime(path)\n                size_bytes = os.path.getsize(path)\n            except OSError:\n                continue\n\n            if (\n                recent_since is not None\n                and modified < recent_since - 2.0\n            ):\n                continue\n\n            result.append(\n                {\n                    "path": path,\n                    "file_name": file_name,\n                    "modified": modified,\n                    "size_bytes": size_bytes,\n                }\n            )\n\n    result.sort(\n        key=lambda item: item["path"].lower()\n    )\n    return result\n\n\ndef file_snapshot(files):\n    return tuple(\n        (\n            item["path"],\n            item["modified"],\n            item["size_bytes"],\n        )\n        for item in files\n    )\n\n\ndef try_convert_single_image_to_png(\n    source_path,\n    png_path,\n):\n    """Best-effort fallback for non-layered image outputs."""\n    try:\n        from PIL import Image\n\n        with Image.open(source_path) as image:\n            image.save(\n                png_path,\n                format="PNG",\n            )\n\n        return os.path.isfile(png_path)\n\n    except Exception:\n        pass\n\n    try:\n        image = mset.Image(source_path)\n        image.writeOut(png_path)\n        return os.path.isfile(png_path)\n\n    except Exception:\n        return False\n\n\ndef organize_output_files(raw_files):\n    texture_sets = all_known_texture_sets()\n    organized = []\n    psd_failures = []\n\n    for raw in raw_files:\n        source_path = raw["path"]\n        extension = os.path.splitext(\n            source_path\n        )[1].lower()\n        texture_set = choose_texture_set_for_file(\n            raw["file_name"],\n            texture_sets,\n        )\n        map_code, map_label = infer_file_map_type(\n            raw["file_name"]\n        )\n\n        destination_directory = os.path.join(\n            JOB["output_directory"],\n            safe_name(texture_set),\n        )\n        os.makedirs(\n            destination_directory,\n            exist_ok=True,\n        )\n\n        destination_path = os.path.join(\n            destination_directory,\n            safe_name(texture_set)\n            + "_"\n            + map_code\n            + ".png",\n        )\n\n        if extension == ".png":\n            if (\n                os.path.normcase(source_path)\n                != os.path.normcase(\n                    destination_path\n                )\n            ):\n                try:\n                    if os.path.isfile(\n                        destination_path\n                    ):\n                        os.remove(\n                            destination_path\n                        )\n\n                    os.replace(\n                        source_path,\n                        destination_path,\n                    )\n\n                except OSError:\n                    shutil.copy2(\n                        source_path,\n                        destination_path,\n                    )\n\n                    try:\n                        os.remove(source_path)\n                    except OSError:\n                        pass\n\n        else:\n            converted = try_convert_single_image_to_png(\n                source_path,\n                destination_path,\n            )\n\n            if not converted:\n                if extension == ".psd":\n                    psd_failures.append(source_path)\n                continue\n\n        try:\n            modified = os.path.getmtime(\n                destination_path\n            )\n            size_bytes = os.path.getsize(\n                destination_path\n            )\n        except OSError:\n            continue\n\n        organized.append(\n            {\n                "path": os.path.normpath(\n                    destination_path\n                ),\n                "file_name": os.path.basename(\n                    destination_path\n                ),\n                "modified": modified,\n                "size_bytes": size_bytes,\n                "map_type": map_label,\n                "map_code": map_code,\n                "texture_set": texture_set,\n                "manager_folder": (\n                    str(texture_set)\n                    + "/Marmoset"\n                ),\n            }\n        )\n\n    if psd_failures and not organized:\n        raise RuntimeError(\n            "Toolbag still produced a layered PSD instead of separate PNG "\n            "maps. The bridge set an explicit .png output path, but this "\n            "Toolbag build kept the scene\'s PSD mode."\n        )\n\n    organized.sort(\n        key=lambda item: item["path"].lower()\n    )\n\n    return organized\n\n\ndef finish_bake(raw_files):\n    global PENDING_BAKE\n    global ROOT_CLEANUP_UNTIL\n\n    organized_files = organize_output_files(\n        raw_files\n    )\n\n    if not organized_files:\n        raise RuntimeError(\n            "Toolbag finished, but no PNG bake maps were produced."\n        )\n\n    manifest_path = JOB["manifest_path"]\n\n    manifest = {\n        "version": 3,\n        "source": "Marmoset Toolbag 5",\n        "generation": time.time(),\n        "painter_project": JOB.get(\n            "painter_project",\n            "",\n        ),\n        "texture_set_names": all_known_texture_sets(),\n        "output_directory": JOB[\n            "output_directory"\n        ],\n        "output_base": BAKER.outputPath,\n        "files": organized_files,\n    }\n\n    write_json_atomic(\n        manifest_path,\n        manifest,\n    )\n\n    scene_path = JOB.get(\n        "scene_path",\n        "",\n    )\n\n    if scene_path:\n        try:\n            mset.saveScene(scene_path)\n        except Exception:\n            traceback.print_exc()\n\n    PENDING_BAKE = None\n\n    clear_raw_output_files()\n    ROOT_CLEANUP_UNTIL = time.time() + 15.0\n\n    message = (\n        "Bake finished. "\n        + str(len(organized_files))\n        + " PNG map(s) sent to Painter."\n    )\n    set_status_text(message)\n    write_status(\n        "baked",\n        message,\n        manifest_path=manifest_path,\n        output_directory=JOB[\n            "output_directory"\n        ],\n        file_count=len(\n            organized_files\n        ),\n        scene_path=scene_path,\n    )\n\n\ndef poll_bake_output():\n    global PENDING_BAKE\n\n    pending = PENDING_BAKE\n\n    if pending is None:\n        return\n\n    now = time.time()\n\n    if now - pending["started_at"] > 900.0:\n        PENDING_BAKE = None\n        message = (\n            "Timed out while waiting for baked maps."\n        )\n        set_status_text(message)\n        write_status(\n            "error",\n            message,\n        )\n        return\n\n    files = collect_raw_output_files(\n        recent_since=pending["started_at"]\n    )\n\n    if not files:\n        return\n\n    snapshot = file_snapshot(files)\n\n    if snapshot == pending.get("snapshot"):\n        pending["stable_checks"] += 1\n    else:\n        pending["snapshot"] = snapshot\n        pending["stable_checks"] = 0\n\n    # Wait for multiple stable checks so Painter never reads half-written files.\n    if pending["stable_checks"] >= 10:\n        finish_bake(files)\n\n\ndef periodic_update():\n    global PENDING_BAKE\n    global ROOT_CLEANUP_UNTIL\n\n    try:\n        poll_bake_output()\n\n        # Some Toolbag builds may recreate root-level images after bake()\n        # returns. Keep cleaning only the temporary root files for a short\n        # period; organized Texture Set subfolders are never touched.\n        if ROOT_CLEANUP_UNTIL > time.time():\n            clear_raw_output_files()\n        elif ROOT_CLEANUP_UNTIL:\n            clear_raw_output_files()\n            ROOT_CLEANUP_UNTIL = 0.0\n\n    except Exception as error:\n        PENDING_BAKE = None\n        traceback.print_exc()\n        set_status_text(\n            "Bridge error: " + str(error)\n        )\n        write_status(\n            "error",\n            str(error),\n            traceback=traceback.format_exc(),\n        )\n\n\ndef bake_and_send():\n    global PENDING_BAKE\n\n    if PENDING_BAKE is not None:\n        set_status_text(\n            "A bake is already running."\n        )\n        return\n\n    try:\n        output_directory = JOB[\n            "output_directory"\n        ]\n        os.makedirs(\n            output_directory,\n            exist_ok=True,\n        )\n\n        # Ensure Toolbag generates one result per low-poly material.\n        ensure_multiple_texture_sets()\n\n        clear_raw_output_files()\n\n        format_members = force_png_output()\n        configured_maps = (\n            configure_enabled_maps()\n        )\n\n        PENDING_BAKE = {\n            "started_at": time.time(),\n            "snapshot": None,\n            "stable_checks": 0,\n        }\n\n        set_status_text(\n            "Baking separate 16-bit PNG maps in Toolbag..."\n        )\n        write_status(\n            "baking",\n            "Toolbag is baking separate 16-bit PNG maps...",\n            output_directory=output_directory,\n            maps=configured_maps,\n            png_settings=format_members,\n            texture_sets=all_known_texture_sets(),\n        )\n\n        BAKER.bake()\n\n        # Do not move files immediately after bake() returns. Toolbag can\n        # still be finalizing them, which caused duplicate root-level PNGs.\n        # The stability watcher will organize them only after they stop\n        # changing for several checks.\n        poll_bake_output()\n\n    except Exception as error:\n        PENDING_BAKE = None\n        traceback.print_exc()\n        set_status_text(\n            "Bake failed: " + str(error)\n        )\n        write_status(\n            "error",\n            str(error),\n            traceback=traceback.format_exc(),\n        )\n\n\ndef build_window():\n    global BRIDGE_WINDOW\n    global STATUS_LABEL\n\n    BRIDGE_WINDOW = mset.UIWindow(\n        "Painter Bake Bridge"\n    )\n\n    try:\n        BRIDGE_WINDOW.width = 430\n    except Exception:\n        pass\n\n    try:\n        project_label = mset.UILabel(\n            "Painter project: "\n            + os.path.basename(\n                JOB.get(\n                    "painter_project",\n                    "",\n                )\n            )\n        )\n        BRIDGE_WINDOW.addElement(\n            project_label\n        )\n        BRIDGE_WINDOW.addReturn()\n\n        sets_label = mset.UILabel(\n            "Texture Sets: "\n            + ", ".join(\n                all_known_texture_sets()\n            )\n        )\n        BRIDGE_WINDOW.addElement(\n            sets_label\n        )\n        BRIDGE_WINDOW.addReturn()\n\n        output_label = mset.UILabel(\n            "Output: "\n            + JOB[\n                "output_directory"\n            ]\n        )\n        BRIDGE_WINDOW.addElement(\n            output_label\n        )\n        BRIDGE_WINDOW.addReturn()\n\n        STATUS_LABEL = mset.UILabel(\n            "Ready. Configure the Baker, then press Bake & Send."\n        )\n        BRIDGE_WINDOW.addElement(\n            STATUS_LABEL\n        )\n        BRIDGE_WINDOW.addReturn()\n\n    except Exception:\n        traceback.print_exc()\n\n    bake_button = mset.UIButton(\n        "Bake & Send to Painter"\n    )\n    bake_button.onClick = bake_and_send\n    BRIDGE_WINDOW.addElement(\n        bake_button\n    )\n\n\ndef create_setup():\n    global BAKER\n\n    low_paths = [\n        os.path.normpath(path)\n        for path in JOB.get(\n            "low_poly_paths",\n            [],\n        )\n        if os.path.isfile(path)\n    ]\n    high_paths = [\n        os.path.normpath(path)\n        for path in JOB.get(\n            "high_poly_paths",\n            [],\n        )\n        if os.path.isfile(path)\n    ]\n\n    if not low_paths:\n        raise RuntimeError(\n            "No valid low-poly file was supplied."\n        )\n\n    if not high_paths:\n        raise RuntimeError(\n            "No valid high-poly file was supplied."\n        )\n\n    os.makedirs(\n        JOB["output_directory"],\n        exist_ok=True,\n    )\n\n    # Clean duplicate root images left by older bridge versions.\n    clear_raw_output_files()\n\n    mset.newScene()\n\n    BAKER = mset.BakerObject()\n    BAKER.name = JOB.get(\n        "baker_name",\n        "Painter Bake Project",\n    )\n\n    # Keep Toolbag in Multiple Texture Sets mode.\n    ensure_multiple_texture_sets()\n\n    try:\n        BAKER.useHiddenMeshes = True\n    except Exception:\n        pass\n\n    force_png_output()\n\n    group = BAKER.addGroup(\n        JOB.get(\n            "group_name",\n            "Bake Group",\n        )\n    )\n\n    low_slot = child_named(\n        group,\n        "Low",\n    )\n    high_slot = child_named(\n        group,\n        "High",\n    )\n\n    if (\n        low_slot is None\n        or high_slot is None\n    ):\n        raise RuntimeError(\n            "Toolbag created a Bake Group, but its High/Low slots "\n            "could not be found."\n        )\n\n    imported_low = []\n    imported_high = []\n\n    for path in low_paths:\n        imported_low.extend(\n            import_under(\n                path,\n                low_slot,\n            )\n        )\n\n    for path in high_paths:\n        imported_high.extend(\n            import_under(\n                path,\n                high_slot,\n            )\n        )\n\n    if (\n        not imported_low\n        or direct_child_count(low_slot) == 0\n    ):\n        raise RuntimeError(\n            "The Low mesh file was opened, but no objects were placed "\n            "inside the Low bake slot."\n        )\n\n    if (\n        not imported_high\n        or direct_child_count(high_slot) == 0\n    ):\n        raise RuntimeError(\n            "The High mesh file was opened, but no objects were placed "\n            "inside the High bake slot."\n        )\n\n    # Importing meshes can refresh the Baker UI, so apply the mode again.\n    ensure_multiple_texture_sets()\n\n    # Keep both High and Low visible when the scene opens.\n    set_visibility_recursive(\n        high_slot,\n        True,\n    )\n    set_visibility_recursive(\n        low_slot,\n        True,\n    )\n\n    try:\n        high_slot.collapsed = False\n        low_slot.collapsed = False\n    except Exception:\n        pass\n\n    # Select both source groups and frame the complete imported setup.\n    try:\n        mset.setSelectedObjects(\n            imported_low + imported_high\n        )\n    except Exception:\n        pass\n\n    try:\n        mset.frameScene()\n    except Exception:\n        pass\n\n    texture_sets = all_known_texture_sets()\n\n    scene_path = JOB.get(\n        "scene_path",\n        "",\n    )\n\n    if scene_path:\n        os.makedirs(\n            os.path.dirname(scene_path),\n            exist_ok=True,\n        )\n        mset.saveScene(scene_path)\n\n    build_window()\n    mset.callbacks.onPeriodicUpdate = (\n        periodic_update\n    )\n\n    message = (\n        "Bake Project created: "\n        + str(len(imported_low))\n        + " Low root(s), "\n        + str(len(imported_high))\n        + " High root(s). Both are visible; Multiple Texture Sets is enabled."\n    )\n    set_status_text(message)\n    write_status(\n        "ready",\n        message,\n        scene_path=scene_path,\n        output_directory=JOB[\n            "output_directory"\n        ],\n        manifest_path=JOB[\n            "manifest_path"\n        ],\n        low_poly_paths=low_paths,\n        high_poly_paths=high_paths,\n        texture_sets=texture_sets,\n        imported_low_count=len(\n            imported_low\n        ),\n        imported_high_count=len(\n            imported_high\n        ),\n    )\n\n\ndef main():\n    global JOB\n    global JOB_PATH\n\n    if len(sys.argv) < 2:\n        raise RuntimeError(\n            "Bridge job path was not supplied."\n        )\n\n    JOB_PATH = os.path.abspath(\n        sys.argv[1]\n    )\n\n    with open(\n        JOB_PATH,\n        "r",\n        encoding="utf-8",\n    ) as stream:\n        JOB = json.load(stream)\n\n    create_setup()\n\n\ntry:\n    main()\nexcept Exception as error:\n    traceback.print_exc()\n\n    try:\n        if not JOB and len(sys.argv) >= 2:\n            with open(\n                sys.argv[1],\n                "r",\n                encoding="utf-8",\n            ) as stream:\n                JOB = json.load(stream)\n    except Exception:\n        pass\n\n    write_status(\n        "error",\n        str(error),\n        traceback=traceback.format_exc(),\n    )\n'

        with open(
            worker_path,
            "w",
            encoding="utf-8",
        ) as stream:
            stream.write(worker_source)

        return worker_path

    @staticmethod
    def safe_external_folder_name(
        value: str,
    ) -> str:
        safe_name = str(value).strip()

        for invalid_character in '<>:"/\\|?*':
            safe_name = safe_name.replace(
                invalid_character,
                "_",
            )

        safe_name = safe_name.rstrip(". ")

        return safe_name or "Texture_Set"

    def marmoset_manifest_path(self) -> Optional[str]:
        cache_dir = self.preview_cache_dir()

        if not cache_dir:
            return None

        return os.path.join(
            cache_dir,
            "Marmoset",
            "_marmoset_bakes_manifest.json",
        )

    def ensure_manager_folder_path(
        self,
        folder_path: str,
    ) -> str:
        normalized = self.normalize_folder_path(
            folder_path
        )

        if not normalized:
            return ""

        folders = self._data.setdefault(
            "folders",
            [],
        )
        parts = normalized.split("/")

        for index in range(
            1,
            len(parts) + 1,
        ):
            partial = "/".join(
                parts[:index]
            )

            if partial not in folders:
                folders.append(partial)

        return normalized

    @staticmethod
    def marmoset_resource_url(
        file_path: str,
    ) -> str:
        local_url = QtCore.QUrl.fromLocalFile(
            os.path.abspath(file_path)
        ).toString(
            QtCore.QUrl.ComponentFormattingOption.FullyEncoded
        )

        return "marmoset+" + local_url

    def scan_marmoset_output_files(
        self,
        marmoset_root: str,
    ) -> tuple[list[dict[str, str]], list[list[Any]]]:
        """Find every preserved Toolbag map in all Texture Set folders.

        The Toolbag manifest contains only files from the latest bake.
        Manually suffixed variants and maps from sets not rebaked in the
        latest pass must therefore also be recovered directly from disk.
        """
        entries = []
        signature = []

        if not os.path.isdir(marmoset_root):
            return entries, signature

        for root, directories, file_names in os.walk(
            marmoset_root
        ):
            directories[:] = [
                directory
                for directory in directories
                if not directory.startswith("_")
            ]

            relative_root = os.path.relpath(
                root,
                marmoset_root,
            )

            # Root-level images are temporary Toolbag bake outputs.
            # Only files inside a Texture Set subfolder are manager assets.
            if relative_root in (".", ""):
                continue

            relative_parts = [
                part
                for part in relative_root.replace(
                    "\\",
                    "/",
                ).split("/")
                if part
            ]

            if not relative_parts:
                continue

            texture_set_name = relative_parts[0]

            for file_name in file_names:
                extension = os.path.splitext(
                    file_name
                )[1].lower()

                if extension not in PREVIEW_EXTENSIONS:
                    continue

                file_path = os.path.normpath(
                    os.path.join(
                        root,
                        file_name,
                    )
                )

                try:
                    stat_result = os.stat(
                        file_path
                    )
                except OSError:
                    continue

                relative_path = os.path.relpath(
                    file_path,
                    marmoset_root,
                ).replace(
                    "\\",
                    "/",
                )
                stem = os.path.splitext(
                    file_name
                )[0]

                signature.append(
                    [
                        relative_path.lower(),
                        int(
                            stat_result.st_mtime_ns
                        ),
                        int(
                            stat_result.st_size
                        ),
                    ]
                )
                entries.append(
                    {
                        "file_path": file_path,
                        "texture_set": (
                            texture_set_name
                        ),
                        "map_type": (
                            self.detect_resource_type(
                                stem
                            )
                        ),
                    }
                )

        signature.sort(
            key=lambda value: value[0]
        )

        return entries, signature

    def import_marmoset_manifest(
        self,
        force: bool = False,
    ) -> int:
        """Merge the newest bake with every Toolbag map still on disk.

        A new bake replaces only the unsuffixed maps it writes. Variants such
        as ``Cube_N_fix.png`` and maps belonging to other Texture Sets remain
        visible for as long as those files still exist in their set folders.
        """
        manifest_path = self.marmoset_manifest_path()

        if not manifest_path:
            return 0

        manifest = {}

        if os.path.isfile(manifest_path):
            try:
                with open(
                    manifest_path,
                    "r",
                    encoding="utf-8",
                ) as stream:
                    manifest = json.load(
                        stream
                    )
            except (
                OSError,
                json.JSONDecodeError,
            ):
                manifest = {}

        generation = manifest.get(
            "generation"
        )
        bridge_settings = (
            self.marmoset_bridge_settings()
        )
        stored_generation = bridge_settings.get(
            "last_manifest_generation"
        )
        is_new_generation = (
            generation is not None
            and generation != stored_generation
        )

        marmoset_root = os.path.dirname(
            manifest_path
        )
        scanned_records, directory_signature = (
            self.scan_marmoset_output_files(
                marmoset_root
            )
        )
        stored_signature = bridge_settings.get(
            "marmoset_directory_signature",
            [],
        )
        directory_changed = (
            directory_signature
            != stored_signature
        )

        if (
            not force
            and not is_new_generation
            and not directory_changed
        ):
            return 0

        # Merge manifest metadata with the complete on-disk file scan.
        # Paths are the stable identity, so the same file can never create
        # several tiles.
        entries_by_path = {}

        for file_record in manifest.get(
            "files",
            [],
        ):
            if isinstance(
                file_record,
                str,
            ):
                file_path = file_record
                map_type = ""
                texture_set_name = ""
            else:
                file_path = file_record.get(
                    "path",
                    "",
                )
                map_type = file_record.get(
                    "map_type",
                    "",
                )
                texture_set_name = str(
                    file_record.get(
                        "texture_set",
                        "",
                    )
                )

            file_path = os.path.normpath(
                str(file_path)
            )

            if (
                not file_path
                or not os.path.isfile(
                    file_path
                )
            ):
                continue

            normalized_path = os.path.normcase(
                os.path.abspath(
                    file_path
                )
            )
            entries_by_path[
                normalized_path
            ] = {
                "file_path": file_path,
                "texture_set": (
                    texture_set_name
                ),
                "map_type": str(
                    map_type
                ),
            }

        for scanned_record in scanned_records:
            file_path = scanned_record[
                "file_path"
            ]
            normalized_path = os.path.normcase(
                os.path.abspath(
                    file_path
                )
            )
            existing = entries_by_path.get(
                normalized_path,
                {},
            )

            entries_by_path[
                normalized_path
            ] = {
                "file_path": file_path,
                "texture_set": (
                    existing.get(
                        "texture_set"
                    )
                    or scanned_record[
                        "texture_set"
                    ]
                ),
                "map_type": (
                    existing.get(
                        "map_type"
                    )
                    or scanned_record[
                        "map_type"
                    ]
                ),
            }

        resources = self._data.setdefault(
            "resources",
            {},
        )
        hidden_urls = set(
            self._data.setdefault(
                "hidden_resource_urls",
                [],
            )
        )
        manually_deleted_urls = set(
            self._data.setdefault(
                "manually_deleted_resource_urls",
                [],
            )
        )

        # Preserve display aliases and any legacy metadata by physical path.
        preserved_by_path = {}

        for url, record in list(
            resources.items()
        ):
            is_marmoset_record = (
                str(url).startswith(
                    "marmoset+"
                )
                or record.get("source")
                == "Marmoset Toolbag 5"
            )

            if not is_marmoset_record:
                continue

            preview_path = record.get(
                "preview_path",
                "",
            )

            if preview_path:
                normalized_path = os.path.normcase(
                    os.path.abspath(
                        os.path.normpath(
                            str(preview_path)
                        )
                    )
                )
                preserved_by_path[
                    normalized_path
                ] = dict(record)

            # Rebuild only the Marmoset section. Painter bake maps and other
            # user resources are not touched.
            resources.pop(
                url,
                None,
            )

        expected_urls = set()
        imported_count = 0

        for normalized_path, entry in sorted(
            entries_by_path.items(),
            key=lambda pair: pair[0],
        ):
            file_path = entry[
                "file_path"
            ]
            extension = os.path.splitext(
                file_path
            )[1].lower()

            if extension not in PREVIEW_EXTENSIONS:
                continue

            texture_set_name = str(
                entry.get(
                    "texture_set",
                    "",
                )
            ).strip()

            if not texture_set_name:
                relative_path = os.path.relpath(
                    file_path,
                    marmoset_root,
                ).replace(
                    "\\",
                    "/",
                )
                texture_set_name = (
                    relative_path.split(
                        "/"
                    )[0]
                    if "/" in relative_path
                    else "Unmatched"
                )

            manager_folder = (
                self.ensure_manager_folder_path(
                    texture_set_name
                    + "/Marmoset"
                )
            )
            url = self.marmoset_resource_url(
                file_path
            )
            expected_urls.add(url)

            # Deleting an archived variant remains respected. A real new bake
            # restores only a file that Toolbag has physically recreated.
            if url in manually_deleted_urls:
                if (
                    is_new_generation
                    and os.path.isfile(
                        file_path
                    )
                ):
                    manually_deleted_urls.discard(
                        url
                    )
                    hidden_urls.discard(url)
                else:
                    hidden_urls.add(url)
                    continue

            file_name = os.path.basename(
                file_path
            )
            stem = os.path.splitext(
                file_name
            )[0]
            record = dict(
                preserved_by_path.get(
                    normalized_path,
                    {},
                )
            )
            old_alias = record.get(
                "alias"
            )
            old_original = record.get(
                "original_name"
            )

            record["original_name"] = stem

            if (
                not old_alias
                or old_alias == old_original
            ):
                record["alias"] = stem

            record["folder"] = (
                manager_folder
            )
            record["type"] = (
                str(
                    entry.get(
                        "map_type",
                        "",
                    )
                )
                or self.detect_resource_type(
                    stem
                )
            )
            record["preview_path"] = (
                file_path
            )
            record["exported_file_name"] = (
                file_name
            )
            record["available"] = True
            record["painter_active"] = False
            record["source"] = (
                "Marmoset Toolbag 5"
            )

            resources[url] = record
            hidden_urls.discard(url)
            imported_count += 1

        # Remove obsolete generated URLs, but retain current manual-deletion
        # markers for files that are still expected.
        hidden_urls = {
            url
            for url in hidden_urls
            if (
                not str(url).startswith(
                    "marmoset+"
                )
                or url in expected_urls
            )
        }
        manually_deleted_urls = {
            url
            for url in manually_deleted_urls
            if (
                not str(url).startswith(
                    "marmoset+"
                )
                or url in expected_urls
            )
        }

        self._data[
            "hidden_resource_urls"
        ] = sorted(hidden_urls)
        self._data[
            "manually_deleted_resource_urls"
        ] = sorted(
            manually_deleted_urls
        )

        bridge_settings[
            "last_manifest_generation"
        ] = generation
        bridge_settings[
            "marmoset_directory_signature"
        ] = directory_signature
        self._last_marmoset_manifest_generation = (
            generation
        )

        self._preview_cache.clear()
        self.save_data()
        self.populate_asset_tiles()

        return imported_count

    def texture_set_names_for_bridge(self) -> list[str]:
        names = []

        try:
            texture_sets = list(
                substance_painter.textureset.all_texture_sets()
            )
        except Exception:
            texture_sets = []

        for texture_set in texture_sets:
            try:
                name = str(
                    texture_set.name()
                ).strip()
            except Exception:
                name = str(texture_set).strip()

            if name and name not in names:
                names.append(name)

        return names

    def active_texture_set_name_for_bridge(self) -> str:
        names = self.texture_set_names_for_bridge()

        try:
            active_stack = (
                substance_painter.textureset.get_active_stack()
            )

            if active_stack is not None:
                texture_set = self.active_texture_set_object()
                active_name = str(texture_set.name())

                if active_name:
                    return active_name
        except Exception:
            pass

        if names:
            return names[0]

        low_path = self.current_low_poly_path()

        if low_path:
            return os.path.splitext(
                os.path.basename(low_path)
            )[0]

        return "Painter"

    def launch_marmoset_bridge(self):
        if not substance_painter.project.is_open():
            self.status_label.setText(
                "Open a Painter project first."
            )
            return

        toolbag_exe = self.detect_toolbag_executable()

        if not toolbag_exe:
            toolbag_exe = self.choose_toolbag_executable()

        if not toolbag_exe:
            self.status_label.setText(
                "Toolbag 5 executable was not selected."
            )
            return

        low_path = self.current_low_poly_path()

        if not low_path:
            self.status_label.setText(
                "Painter could not resolve the current low-poly mesh path."
            )
            return

        high_paths = self.painter_high_poly_paths()

        if not high_paths:
            high_paths = self.choose_high_poly_paths()

        if not high_paths:
            self.status_label.setText(
                "No high-poly mesh path was found or selected."
            )
            return

        worker_path = self.write_marmoset_worker()
        bridge_directory = self.marmoset_bridge_directory()

        if not worker_path or not bridge_directory:
            self.status_label.setText(
                "Save the Painter project before launching Toolbag."
            )
            return

        project_path = str(
            substance_painter.project.file_path()
        )
        project_name = os.path.splitext(
            os.path.basename(project_path)
        )[0]
        texture_set_names = self.texture_set_names_for_bridge()
        group_name = project_name

        status_path = os.path.join(
            bridge_directory,
            "marmoset_bridge_status.json",
        )
        job_path = os.path.join(
            bridge_directory,
            "marmoset_bridge_job.json",
        )
        scene_path = os.path.join(
            bridge_directory,
            project_name + "_Bake.tbscene",
        )
        output_directory = os.path.join(
            cache_dir := self.preview_cache_dir(),
            "Marmoset",
        )
        manifest_path = os.path.join(
            output_directory,
            "_marmoset_bakes_manifest.json",
        )

        try:
            if os.path.isfile(status_path):
                os.remove(status_path)
        except OSError:
            traceback.print_exc()

        job = {
            "version": 1,
            "painter_project": project_path,
            "baker_name": project_name + " Bake",
            "group_name": group_name,
            "low_poly_paths": [low_path],
            "high_poly_paths": high_paths,
            "scene_path": scene_path,
            "status_path": status_path,
            "output_directory": output_directory,
            "manifest_path": manifest_path,
            "texture_set_names": texture_set_names,
            "output_base_name": project_name,
        }

        with open(
            job_path,
            "w",
            encoding="utf-8",
        ) as stream:
            json.dump(
                job,
                stream,
                ensure_ascii=False,
                indent=4,
            )

        try:
            creation_flags = getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )

            self._marmoset_process = subprocess.Popen(
                [
                    toolbag_exe,
                    worker_path,
                    job_path,
                ],
                creationflags=creation_flags,
            )

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Toolbag 5 could not be launched. See Python Console."
            )
            return

        self._marmoset_status_path = status_path
        self._marmoset_status_timer.start()

        self.status_label.setText(
            "Launching Toolbag 5 and creating the Bake Project..."
        )

    def check_marmoset_bridge_status(self):
        status_path = self._marmoset_status_path

        if not status_path or not os.path.isfile(status_path):
            return

        try:
            with open(
                status_path,
                "r",
                encoding="utf-8",
            ) as stream:
                status = json.load(stream)
        except (OSError, json.JSONDecodeError):
            return

        state = str(
            status.get("state", "")
        ).lower()
        message = str(
            status.get("message", "")
        )

        if message:
            self.status_label.setText(message)

        if state == "baked":
            imported_count = self.import_marmoset_manifest(
                force=False
            )

            self.status_label.setText(
                f"Marmoset bake received: "
                f"{imported_count} map(s)."
            )

        elif state == "error":
            print(
                "[BakeManager][MarmosetBridge] "
                + str(
                    status.get(
                        "traceback",
                        message,
                    )
                )
            )

    # ------------------------------------------------------------------
    # Folder context menu
    # ------------------------------------------------------------------

    def show_folder_context_menu(self, position):
        item = self.folder_tree.itemAt(position)

        if item is not None:
            self.folder_tree.setCurrentItem(item)

        menu = QtWidgets.QMenu(self)

        refresh_action = menu.addAction("Refresh")
        menu.addSeparator()

        new_folder_action = menu.addAction("New Folder")

        rename_action = None
        delete_action = None

        folder_path = self.current_folder_path()

        if folder_path:
            rename_action = menu.addAction("Rename Folder")

            if folder_path not in (
                DEFAULT_BAKE_FOLDER,
                DEFAULT_IMPORTED_FOLDER,
            ):
                delete_action = menu.addAction("Delete Folder")

        chosen = menu.exec(
            self.folder_tree.viewport().mapToGlobal(position)
        )

        if chosen == refresh_action:
            self.refresh_manager()

        elif chosen == new_folder_action:
            self.create_folder()

        elif rename_action is not None and chosen == rename_action:
            self.rename_folder()

        elif delete_action is not None and chosen == delete_action:
            self.delete_folder()

    def create_folder(self):
        parent_path = self.current_folder_path()

        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "New Folder",
            "Folder name:",
            text="New Folder",
        )

        if not accepted:
            return

        name = name.strip().replace("/", "_").replace("\\", "_")

        if not name:
            return

        new_path = (
            name
            if not parent_path
            else parent_path + "/" + name
        )

        new_path = self.normalize_folder_path(new_path)

        folders = self._data.setdefault("folders", [])

        if new_path in folders:
            QtWidgets.QMessageBox.information(
                self,
                "New Folder",
                "A folder with this name already exists.",
            )
            return

        folders.append(new_path)
        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText(
            f"Created folder: {name}"
        )

    def rename_folder(self):
        old_path = self.current_folder_path()

        if not old_path:
            return

        old_name = old_path.split("/")[-1]
        parent_path = "/".join(old_path.split("/")[:-1])

        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Folder",
            "New name:",
            text=old_name,
        )

        if not accepted:
            return

        new_name = (
            new_name.strip()
            .replace("/", "_")
            .replace("\\", "_")
        )

        if not new_name or new_name == old_name:
            return

        new_path = (
            new_name
            if not parent_path
            else parent_path + "/" + new_name
        )

        folders = self._data.get("folders", [])

        if new_path in folders:
            QtWidgets.QMessageBox.information(
                self,
                "Rename Folder",
                "A folder with this name already exists.",
            )
            return

        updated_folders = []

        for folder in folders:
            if folder == old_path:
                updated_folders.append(new_path)

            elif folder.startswith(old_path + "/"):
                updated_folders.append(
                    new_path + folder[len(old_path):]
                )

            else:
                updated_folders.append(folder)

        self._data["folders"] = updated_folders

        folder_previews = self._data.setdefault(
            "folder_previews",
            {},
        )

        if old_path in folder_previews:
            folder_previews[new_path] = folder_previews.pop(
                old_path
            )

        for preview_folder in list(folder_previews):
            if preview_folder.startswith(old_path + "/"):
                migrated_preview_folder = (
                    new_path
                    + preview_folder[len(old_path):]
                )
                folder_previews[migrated_preview_folder] = (
                    folder_previews.pop(preview_folder)
                )

        for record in self._data.get(
            "resources",
            {},
        ).values():
            folder = record.get("folder", "")

            if folder == old_path:
                record["folder"] = new_path

            elif folder.startswith(old_path + "/"):
                record["folder"] = (
                    new_path + folder[len(old_path):]
                )

        self.save_data()
        self._current_folder_path = parent_path
        self.populate_asset_tiles()

    def delete_folder(self):
        folder_path = self.current_folder_path()

        if not folder_path:
            return

        result = QtWidgets.QMessageBox.question(
            self,
            "Delete Folder",
            (
                f"Delete folder '{folder_path}'?\n\n"
                "Resources inside it will be moved to "
                "'Imported Textures'."
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )

        if result != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self._data["folders"] = [
            folder
            for folder in self._data.get("folders", [])
            if (
                folder != folder_path
                and not folder.startswith(folder_path + "/")
            )
        ]

        for record in self._data.get(
            "resources",
            {},
        ).values():
            folder = record.get("folder", "")

            if (
                folder == folder_path
                or folder.startswith(folder_path + "/")
            ):
                record["folder"] = DEFAULT_IMPORTED_FOLDER

        self.save_data()
        self._current_folder_path = parent_path
        self.populate_asset_tiles()

    # ------------------------------------------------------------------
    # Asset context menu
    # ------------------------------------------------------------------

    def show_asset_context_menu(self, position):
        item = self.asset_list.itemAt(position)

        menu = QtWidgets.QMenu(self)
        refresh_action = menu.addAction("Refresh")

        marmoset_menu = menu.addMenu("Marmoset Bridge")
        marmoset_launch_action = marmoset_menu.addAction(
            "Create Bake Setup in Toolbag 5"
        )
        common_separator = menu.addSeparator()

        if item is None:
            # Empty-area order:
            # Refresh → New Folder → separator → Marmoset Bridge
            menu.removeAction(common_separator)
            menu.removeAction(
                marmoset_menu.menuAction()
            )
            new_folder_action = menu.addAction(
                "New Folder"
            )
            menu.addSeparator()
            menu.addAction(
                marmoset_menu.menuAction()
            )

            chosen = menu.exec(
                self.asset_list.viewport().mapToGlobal(
                    position
                )
            )

            if chosen == refresh_action:
                self.refresh_and_generate_previews()

            elif chosen == marmoset_launch_action:
                self.launch_marmoset_bridge()

            elif chosen == new_folder_action:
                self.create_folder()

            return

        # Right-clicking an already selected texture keeps the whole
        # multi-selection. Right-clicking an unselected item starts a new
        # single-item selection, matching normal file-browser behavior.
        if (
            item.data(ROLE_KIND) == KIND_RESOURCE
            and not item.isSelected()
        ):
            self.asset_list.clearSelection()
            item.setSelected(True)

        self.asset_list.setCurrentItem(item)

        kind = item.data(ROLE_KIND)

        if kind == KIND_FOLDER:
            folder_path = item.data(
                ROLE_FOLDER_PATH
            ) or ""

            rename_folder_action = None
            delete_folder_action = None

            if item.text() != "..":
                # Folder menu:
                # Refresh → Rename → Delete → Marmoset Bridge
                menu.removeAction(
                    common_separator
                )
                menu.removeAction(
                    marmoset_menu.menuAction()
                )

                rename_folder_action = menu.addAction(
                    "Rename"
                )

                if folder_path not in (
                    DEFAULT_BAKE_FOLDER,
                    DEFAULT_IMPORTED_FOLDER,
                ):
                    delete_folder_action = menu.addAction(
                        "Delete"
                    )

                menu.addSeparator()
                menu.addAction(
                    marmoset_menu.menuAction()
                )

            chosen = menu.exec(
                self.asset_list.viewport().mapToGlobal(
                    position
                )
            )

            if chosen == refresh_action:
                self.refresh_and_generate_previews()

            elif chosen == marmoset_launch_action:
                self.launch_marmoset_bridge()

            elif (
                rename_folder_action is not None
                and chosen == rename_folder_action
            ):
                self.rename_folder_path(
                    folder_path
                )

            elif (
                delete_folder_action is not None
                and chosen == delete_folder_action
            ):
                self.delete_folder_path(
                    folder_path
                )

            return

        url = item.data(
            ROLE_RESOURCE_URL
        )
        record = self._data.get(
            "resources",
            {},
        ).get(
            url,
            {},
        )

        selected_resource_urls = []

        for selected_item in self.asset_list.selectedItems():
            if (
                selected_item.data(ROLE_KIND)
                != KIND_RESOURCE
            ):
                continue

            selected_url = selected_item.data(
                ROLE_RESOURCE_URL
            )

            if (
                selected_url
                and selected_url
                not in selected_resource_urls
            ):
                selected_resource_urls.append(
                    selected_url
                )

        if url and url not in selected_resource_urls:
            selected_resource_urls.append(url)

        assign_fill_action = None
        assign_mesh_map_action = None
        rename_action = None
        delete_action = None
        suffix_actions = {}

        if record.get("preview_path"):
            assign_fill_action = menu.addAction(
                "Assign to Selected Fill Layer..."
            )
            assign_mesh_map_action = menu.addAction(
                "Assign to Texture Set..."
            )

            menu.addSeparator()

            suffix_actions = self.build_suffix_menus(
                menu,
                selected_resource_urls,
            )

            menu.addSeparator()
            rename_action = menu.addAction("Rename")
            delete_action = menu.addAction("Delete")

        chosen = menu.exec(
            self.asset_list.viewport().mapToGlobal(
                position
            )
        )

        if chosen == refresh_action:
            self.refresh_and_generate_previews()

        elif chosen == marmoset_launch_action:
            self.launch_marmoset_bridge()

        elif (
            assign_fill_action is not None
            and chosen == assign_fill_action
        ):
            self.handle_drop_to_properties(
                [item],
                QtGui.QCursor.pos(),
            )

        elif (
            assign_mesh_map_action is not None
            and chosen == assign_mesh_map_action
        ):
            self.handle_drop_to_texture_set_settings(
                [item],
                QtGui.QCursor.pos(),
            )

        elif chosen in suffix_actions:
            operation, suffix = suffix_actions[
                chosen
            ]

            if operation == "add":
                self.append_suffix_to_assets(
                    selected_resource_urls,
                    suffix,
                )

            elif operation == "remove":
                self.remove_suffix_from_assets(
                    selected_resource_urls,
                    suffix,
                )

            elif operation == "remove_last":
                self.remove_last_suffix_from_assets(
                    selected_resource_urls
                )

        elif (
            rename_action is not None
            and chosen == rename_action
        ):
            self.rename_exported_file(item)

        elif (
            delete_action is not None
            and chosen == delete_action
        ):
            self.delete_assets_files_and_records(
                selected_resource_urls
            )

    @staticmethod
    def normalize_suffix_token(
        value: str,
    ) -> str:
        """Return a safe filename token without leading separators."""
        token = str(value).strip()

        while token.startswith(("_", "-", " ")):
            token = token[1:]

        for invalid_character in '<>:"/\\|?*':
            token = token.replace(
                invalid_character,
                "_",
            )

        token = re.sub(
            r"\s+",
            "_",
            token,
        )
        token = re.sub(
            r"_+",
            "_",
            token,
        )

        return token.strip("._- ")

    def custom_suffixes(self) -> list[str]:
        raw_suffixes = self._data.setdefault(
            "custom_suffixes",
            [],
        )
        result = []

        for value in raw_suffixes:
            token = self.normalize_suffix_token(
                value
            )

            if (
                token
                and token.lower()
                not in {
                    existing.lower()
                    for existing in result
                }
            ):
                result.append(token)

        if result != raw_suffixes:
            self._data["custom_suffixes"] = result

        return result

    @staticmethod
    def standard_type_suffixes() -> tuple[str, ...]:
        return (
            "N",
            "C",
            "AO",
            "BN",
            "WSN",
            "ID",
            "P",
            "T",
            "H",
            "O",
        )

    def resource_stem_for_url(
        self,
        resource_url: str,
    ) -> str:
        record = self._data.get(
            "resources",
            {},
        ).get(
            resource_url,
            {},
        )
        file_path = record.get(
            "preview_path",
            "",
        )

        if not file_path:
            return ""

        return os.path.splitext(
            os.path.basename(
                str(file_path)
            )
        )[0]

    def suffix_is_present(
        self,
        resource_urls: list[str],
        suffix: str,
    ) -> bool:
        token = self.normalize_suffix_token(
            suffix
        )

        if not token:
            return False

        ending = "_" + token.lower()

        for resource_url in resource_urls:
            stem = self.resource_stem_for_url(
                resource_url
            )

            if stem.lower().endswith(ending):
                return True

        return False

    def build_suffix_menus(
        self,
        root_menu: QtWidgets.QMenu,
        resource_urls: list[str],
    ) -> dict[QtGui.QAction, tuple[str, str]]:
        """Build batch-aware Add Suffix and Remove Suffix menus."""
        action_map = {}
        self.build_add_suffix_menu(
            root_menu,
            resource_urls,
            action_map,
        )
        self.build_remove_suffix_menu(
            root_menu,
            resource_urls,
            action_map,
        )

        return action_map

    def build_add_suffix_menu(
        self,
        root_menu: QtWidgets.QMenu,
        resource_urls: list[str],
        action_map: dict[
            QtGui.QAction,
            tuple[str, str],
        ],
    ):
        suffix_menu = root_menu.addMenu(
            "Add Suffix"
        )

        set_menu = suffix_menu.addMenu(
            "Set"
        )
        texture_set_names = (
            self.texture_set_names_for_bridge()
        )

        if texture_set_names:
            for texture_set_name in texture_set_names:
                action = set_menu.addAction(
                    texture_set_name
                )
                action_map[action] = (
                    "add",
                    texture_set_name,
                )
        else:
            empty_action = set_menu.addAction(
                "No Texture Sets"
            )
            empty_action.setEnabled(False)

        type_menu = suffix_menu.addMenu(
            "Type"
        )

        for type_suffix in self.standard_type_suffixes():
            action = type_menu.addAction(
                "_" + type_suffix
            )
            action_map[action] = (
                "add",
                type_suffix,
            )

        fixes_menu = suffix_menu.addMenu(
            "Fixes"
        )
        add_new_action = fixes_menu.addAction(
            "Add New..."
        )
        add_new_action.triggered.connect(
            lambda _checked=False: (
                self.add_new_custom_suffix(
                    resource_urls
                )
            )
        )

        custom_suffixes = self.custom_suffixes()

        if custom_suffixes:
            fixes_menu.addSeparator()

        for custom_suffix in custom_suffixes:
            self.add_custom_suffix_row(
                fixes_menu,
                root_menu,
                resource_urls,
                custom_suffix,
            )

    def build_remove_suffix_menu(
        self,
        root_menu: QtWidgets.QMenu,
        resource_urls: list[str],
        action_map: dict[
            QtGui.QAction,
            tuple[str, str],
        ],
    ):
        remove_menu = root_menu.addMenu(
            "Remove Suffix"
        )

        has_any_suffix = any(
            "_" in self.resource_stem_for_url(
                resource_url
            )
            for resource_url in resource_urls
        )

        remove_last_action = (
            remove_menu.addAction(
                "Remove Last Suffix"
            )
        )
        remove_last_action.setEnabled(
            has_any_suffix
        )

        if has_any_suffix:
            action_map[
                remove_last_action
            ] = (
                "remove_last",
                "",
            )

        set_menu = remove_menu.addMenu(
            "Set"
        )
        set_count = 0

        for texture_set_name in (
            self.texture_set_names_for_bridge()
        ):
            if not self.suffix_is_present(
                resource_urls,
                texture_set_name,
            ):
                continue

            action = set_menu.addAction(
                texture_set_name
            )
            action_map[action] = (
                "remove",
                texture_set_name,
            )
            set_count += 1

        if not set_count:
            empty_action = set_menu.addAction(
                "No matching suffixes"
            )
            empty_action.setEnabled(False)

        type_menu = remove_menu.addMenu(
            "Type"
        )
        type_count = 0

        for type_suffix in self.standard_type_suffixes():
            if not self.suffix_is_present(
                resource_urls,
                type_suffix,
            ):
                continue

            action = type_menu.addAction(
                "_" + type_suffix
            )
            action_map[action] = (
                "remove",
                type_suffix,
            )
            type_count += 1

        if not type_count:
            empty_action = type_menu.addAction(
                "No matching suffixes"
            )
            empty_action.setEnabled(False)

        fixes_menu = remove_menu.addMenu(
            "Fixes"
        )
        fixes_count = 0

        for custom_suffix in self.custom_suffixes():
            if not self.suffix_is_present(
                resource_urls,
                custom_suffix,
            ):
                continue

            action = fixes_menu.addAction(
                custom_suffix
            )
            action_map[action] = (
                "remove",
                custom_suffix,
            )
            fixes_count += 1

        if not fixes_count:
            empty_action = fixes_menu.addAction(
                "No matching suffixes"
            )
            empty_action.setEnabled(False)

    def add_custom_suffix_row(
        self,
        fixes_menu: QtWidgets.QMenu,
        root_menu: QtWidgets.QMenu,
        resource_urls: list[str],
        suffix: str,
    ):
        """Create a suffix row with an Apply button and a delete cross."""
        row_widget = QtWidgets.QWidget(
            fixes_menu
        )
        row_layout = QtWidgets.QHBoxLayout(
            row_widget
        )
        row_layout.setContentsMargins(
            5,
            1,
            3,
            1,
        )
        row_layout.setSpacing(3)

        apply_button = QtWidgets.QPushButton(
            suffix,
            row_widget,
        )
        apply_button.setFlat(True)
        apply_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor
        )
        apply_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        apply_button.setStyleSheet(
            "QPushButton {"
            " text-align: left;"
            " padding: 3px 8px;"
            " border: none;"
            " background: transparent;"
            "}"
            "QPushButton:hover {"
            " background: rgba(255,255,255,25);"
            "}"
        )

        delete_button = QtWidgets.QToolButton(
            row_widget
        )
        delete_button.setText("×")
        delete_button.setToolTip(
            "Delete saved suffix"
        )
        delete_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor
        )
        delete_button.setAutoRaise(True)
        delete_button.setFixedSize(
            22,
            22,
        )

        row_layout.addWidget(
            apply_button,
            1,
        )
        row_layout.addWidget(
            delete_button,
            0,
        )

        widget_action = QtWidgets.QWidgetAction(
            fixes_menu
        )
        widget_action.setDefaultWidget(
            row_widget
        )
        fixes_menu.addAction(
            widget_action
        )

        apply_button.clicked.connect(
            lambda _checked=False, value=suffix: (
                self.append_suffix_to_assets(
                    resource_urls,
                    value,
                ),
                root_menu.close(),
            )
        )
        delete_button.clicked.connect(
            lambda _checked=False, value=suffix: (
                self.remove_custom_suffix(
                    value
                ),
                root_menu.close(),
            )
        )

    def add_new_custom_suffix(
        self,
        resource_urls: list[str],
    ):
        value, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Add Custom Suffix",
            "New suffix:",
        )

        if not accepted:
            return

        token = self.normalize_suffix_token(
            value
        )

        if not token:
            return

        suffixes = self.custom_suffixes()

        if token.lower() not in {
            existing.lower()
            for existing in suffixes
        }:
            suffixes.append(token)
            self._data["custom_suffixes"] = (
                suffixes
            )
            self.save_data()

        self.append_suffix_to_assets(
            resource_urls,
            token,
        )

    def remove_custom_suffix(
        self,
        suffix: str,
    ):
        token = self.normalize_suffix_token(
            suffix
        )
        suffixes = [
            existing
            for existing in self.custom_suffixes()
            if existing.lower() != token.lower()
        ]
        self._data["custom_suffixes"] = suffixes
        self.save_data()

        self.status_label.setText(
            f"Removed saved suffix: {token}"
        )

    def update_marmoset_manifest_file_paths(
        self,
        renamed_paths: list[
            tuple[str, str]
        ],
    ):
        """Update all renamed Toolbag files in one manifest write."""
        if not renamed_paths:
            return

        manifest_path = self.marmoset_manifest_path()

        if (
            not manifest_path
            or not os.path.isfile(manifest_path)
        ):
            return

        try:
            with open(
                manifest_path,
                "r",
                encoding="utf-8",
            ) as stream:
                manifest = json.load(stream)
        except (OSError, json.JSONDecodeError):
            return

        path_map = {
            os.path.normcase(
                os.path.abspath(old_path)
            ): os.path.normpath(new_path)
            for old_path, new_path in renamed_paths
        }
        changed = False

        for file_record in manifest.get(
            "files",
            [],
        ):
            if not isinstance(
                file_record,
                dict,
            ):
                continue

            record_path = os.path.normcase(
                os.path.abspath(
                    os.path.normpath(
                        str(
                            file_record.get(
                                "path",
                                "",
                            )
                        )
                    )
                )
            )
            new_path = path_map.get(
                record_path
            )

            if not new_path:
                continue

            file_record["path"] = new_path
            file_record["file_name"] = (
                os.path.basename(new_path)
            )
            changed = True

        if not changed:
            return

        generation = time.time()
        manifest["generation"] = generation
        temporary_path = (
            manifest_path + ".tmp"
        )

        try:
            with open(
                temporary_path,
                "w",
                encoding="utf-8",
            ) as stream:
                json.dump(
                    manifest,
                    stream,
                    ensure_ascii=False,
                    indent=4,
                )

            os.replace(
                temporary_path,
                manifest_path,
            )

            self.marmoset_bridge_settings()[
                "last_manifest_generation"
            ] = generation
            self._last_marmoset_manifest_generation = (
                generation
            )

        except OSError:
            traceback.print_exc()

    def update_marmoset_manifest_file_path(
        self,
        old_path: str,
        new_path: str,
    ):
        self.update_marmoset_manifest_file_paths(
            [
                (
                    old_path,
                    new_path,
                )
            ]
        )

    def rename_resource_file_stem(
        self,
        resource_url: str,
        new_stem: str,
    ) -> tuple[
        bool,
        str,
        str,
        str,
    ]:
        """Rename one texture without refreshing the UI.

        Returns: success, resulting URL, old path, new path.
        """
        resources = self._data.setdefault(
            "resources",
            {},
        )
        record = resources.get(
            resource_url
        )

        if record is None:
            return (
                False,
                resource_url,
                "",
                "",
            )

        old_path = record.get(
            "preview_path"
        )

        if (
            not old_path
            or not os.path.isfile(
                str(old_path)
            )
        ):
            return (
                False,
                resource_url,
                "",
                "",
            )

        old_path = os.path.normpath(
            str(old_path)
        )
        old_directory = os.path.dirname(
            old_path
        )
        _old_stem, extension = os.path.splitext(
            os.path.basename(old_path)
        )
        new_path = os.path.join(
            old_directory,
            new_stem + extension,
        )

        if (
            os.path.normcase(new_path)
            == os.path.normcase(old_path)
        ):
            return (
                False,
                resource_url,
                old_path,
                old_path,
            )

        if os.path.exists(new_path):
            return (
                False,
                resource_url,
                old_path,
                new_path,
            )

        candidate_names = {
            self.normalized_resource_name(
                _old_stem
            ),
            self.normalized_resource_name(
                new_stem
            ),
        }
        candidate_urls = (
            self.project_resource_urls_for_record(
                record,
                candidate_names,
            )
        )
        texture_set_name = str(
            record.get(
                "texture_set_name",
                "",
            )
        ).strip()

        if not texture_set_name:
            folder_path = str(
                record.get(
                    "folder",
                    "",
                )
            ).replace(
                "\\",
                "/",
            )
            texture_set_name = (
                folder_path.split(
                    "/",
                    1,
                )[0]
                if folder_path
                else ""
            )

        pending_bindings = (
            self.source_bindings_for_resources(
                texture_set_name or None,
                candidate_urls,
                candidate_names,
            )
        )

        try:
            os.rename(
                old_path,
                new_path,
            )
        except OSError:
            traceback.print_exc()
            return (
                False,
                resource_url,
                old_path,
                new_path,
            )

        record["preview_path"] = (
            os.path.normpath(new_path)
        )
        record["original_name"] = new_stem
        record["alias"] = new_stem
        record["exported_file_name"] = (
            os.path.basename(new_path)
        )

        if pending_bindings:
            try:
                new_resource_id = (
                    self.import_texture_resource(
                        new_path
                    )
                )
                replaced = (
                    self.replace_layer_source_bindings(
                        pending_bindings,
                        new_resource_id,
                    )
                )

                if replaced:
                    painter_urls = list(
                        record.get(
                            "painter_resource_urls",
                            [],
                        )
                    )
                    new_painter_url = (
                        new_resource_id.url()
                    )

                    if (
                        new_painter_url
                        not in painter_urls
                    ):
                        painter_urls.append(
                            new_painter_url
                        )

                    record[
                        "painter_resource_urls"
                    ] = painter_urls
                    record[
                        "last_relinked_resource_url"
                    ] = new_painter_url
                    record[
                        "relinked_layer_sources"
                    ] = replaced

            except Exception:
                traceback.print_exc()

        resulting_url = resource_url

        if str(resource_url).startswith(
            "marmoset+"
        ):
            resulting_url = (
                self.marmoset_resource_url(
                    new_path
                )
            )

            if resulting_url != resource_url:
                resources.pop(
                    resource_url,
                    None,
                )
                resources[
                    resulting_url
                ] = record

                hidden_urls = set(
                    self._data.setdefault(
                        "hidden_resource_urls",
                        [],
                    )
                )
                deleted_urls = set(
                    self._data.setdefault(
                        "manually_deleted_resource_urls",
                        [],
                    )
                )

                if resource_url in hidden_urls:
                    hidden_urls.discard(
                        resource_url
                    )
                    hidden_urls.add(
                        resulting_url
                    )

                if resource_url in deleted_urls:
                    deleted_urls.discard(
                        resource_url
                    )
                    deleted_urls.add(
                        resulting_url
                    )

                self._data[
                    "hidden_resource_urls"
                ] = sorted(hidden_urls)
                self._data[
                    "manually_deleted_resource_urls"
                ] = sorted(deleted_urls)

        return (
            True,
            resulting_url,
            old_path,
            os.path.normpath(new_path),
        )

    def finalize_suffix_batch(
        self,
        renamed_paths: list[
            tuple[str, str]
        ],
        status_text: str,
    ):
        self.update_marmoset_manifest_file_paths(
            renamed_paths
        )
        self._preview_cache.clear()
        self.save_data()
        self.populate_asset_tiles()
        self.status_label.setText(
            status_text
        )

    def append_suffix_to_assets(
        self,
        resource_urls: list[str],
        suffix: str,
    ):
        token = self.normalize_suffix_token(
            suffix
        )

        if not token:
            return

        suffix_text = "_" + token
        renamed_paths = []
        renamed_count = 0
        skipped_count = 0

        for resource_url in list(
            dict.fromkeys(resource_urls)
        ):
            stem = self.resource_stem_for_url(
                resource_url
            )

            if not stem:
                skipped_count += 1
                continue

            if stem.lower().endswith(
                suffix_text.lower()
            ):
                skipped_count += 1
                continue

            success, _new_url, old_path, new_path = (
                self.rename_resource_file_stem(
                    resource_url,
                    stem + suffix_text,
                )
            )

            if success:
                renamed_paths.append(
                    (
                        old_path,
                        new_path,
                    )
                )
                renamed_count += 1
            else:
                skipped_count += 1

        self.finalize_suffix_batch(
            renamed_paths,
            (
                f"Added {suffix_text} to "
                f"{renamed_count} texture(s)"
                + (
                    f"; skipped {skipped_count}."
                    if skipped_count
                    else "."
                )
            ),
        )

    def remove_suffix_from_assets(
        self,
        resource_urls: list[str],
        suffix: str,
    ):
        token = self.normalize_suffix_token(
            suffix
        )

        if not token:
            return

        suffix_text = "_" + token
        renamed_paths = []
        renamed_count = 0
        skipped_count = 0

        for resource_url in list(
            dict.fromkeys(resource_urls)
        ):
            stem = self.resource_stem_for_url(
                resource_url
            )

            if (
                not stem
                or not stem.lower().endswith(
                    suffix_text.lower()
                )
            ):
                skipped_count += 1
                continue

            new_stem = stem[
                :-len(suffix_text)
            ].rstrip("._- ")

            if not new_stem:
                skipped_count += 1
                continue

            success, _new_url, old_path, new_path = (
                self.rename_resource_file_stem(
                    resource_url,
                    new_stem,
                )
            )

            if success:
                renamed_paths.append(
                    (
                        old_path,
                        new_path,
                    )
                )
                renamed_count += 1
            else:
                skipped_count += 1

        self.finalize_suffix_batch(
            renamed_paths,
            (
                f"Removed {suffix_text} from "
                f"{renamed_count} texture(s)"
                + (
                    f"; skipped {skipped_count}."
                    if skipped_count
                    else "."
                )
            ),
        )

    def remove_last_suffix_from_assets(
        self,
        resource_urls: list[str],
    ):
        renamed_paths = []
        renamed_count = 0
        skipped_count = 0

        for resource_url in list(
            dict.fromkeys(resource_urls)
        ):
            stem = self.resource_stem_for_url(
                resource_url
            )

            if (
                not stem
                or "_" not in stem
            ):
                skipped_count += 1
                continue

            new_stem = stem.rsplit(
                "_",
                1,
            )[0].rstrip("._- ")

            if not new_stem:
                skipped_count += 1
                continue

            success, _new_url, old_path, new_path = (
                self.rename_resource_file_stem(
                    resource_url,
                    new_stem,
                )
            )

            if success:
                renamed_paths.append(
                    (
                        old_path,
                        new_path,
                    )
                )
                renamed_count += 1
            else:
                skipped_count += 1

        self.finalize_suffix_batch(
            renamed_paths,
            (
                "Removed the last suffix from "
                f"{renamed_count} texture(s)"
                + (
                    f"; skipped {skipped_count}."
                    if skipped_count
                    else "."
                )
            ),
        )

    def create_color_swatch_icon(
        self,
        color_key: str,
    ) -> Optional[QtGui.QIcon]:
        """Create a small gradient swatch for the context menu."""
        palette = COLOR_LABELS.get(
            color_key
        )

        if palette is None:
            return None

        pixmap = QtGui.QPixmap(
            18,
            18,
        )
        pixmap.fill(
            QtCore.Qt.GlobalColor.transparent
        )

        painter = QtGui.QPainter(pixmap)

        try:
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.Antialiasing,
                True,
            )

            light_color, middle_color, dark_color = palette
            gradient = QtGui.QLinearGradient(
                0,
                0,
                0,
                18,
            )
            gradient.setColorAt(
                0.0,
                light_color,
            )
            gradient.setColorAt(
                0.5,
                middle_color,
            )
            gradient.setColorAt(
                1.0,
                dark_color,
            )

            painter.setPen(
                QtGui.QPen(
                    dark_color,
                    1.0,
                )
            )
            painter.setBrush(
                QtGui.QBrush(gradient)
            )
            painter.drawRoundedRect(
                QtCore.QRectF(
                    2,
                    2,
                    14,
                    14,
                ),
                2.5,
                2.5,
            )

        finally:
            painter.end()

        return QtGui.QIcon(pixmap)

    def set_asset_color_label(
        self,
        item: QtWidgets.QListWidgetItem,
        color_key: str,
    ):
        """Save and immediately redraw a texture's color frame."""
        if color_key not in COLOR_LABELS:
            color_key = "none"

        url = item.data(
            ROLE_RESOURCE_URL
        )
        record = self._data.get(
            "resources",
            {},
        ).get(url)

        if record is None:
            return

        record["color_label"] = color_key

        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText(
            "Color label: "
            + COLOR_LABEL_NAMES[color_key]
        )

    def find_3d_viewport(self):
        """Return Painter's visible 3D PaintViewer."""
        candidates = []

        for widget in QtWidgets.QApplication.allWidgets():
            try:
                if (
                    widget.objectName() == "Viewer3D"
                    and widget.isVisible()
                ):
                    candidates.append(widget)
            except RuntimeError:
                continue

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda widget: (
                widget.width() * widget.height()
            ),
        )

    def activate_texture_set_for_folder(
        self,
        folder_path: str,
    ) -> bool:
        """Activate the Texture Set whose name matches the folder name."""
        folder_name = self.normalize_folder_path(
            folder_path
        ).split("/")[-1]

        try:
            texture_sets = list(
                substance_painter.textureset.all_texture_sets()
            )
        except Exception:
            return False

        for texture_set in texture_sets:
            try:
                texture_set_name = texture_set.name()
            except Exception:
                texture_set_name = str(texture_set)

            if str(texture_set_name) != folder_name:
                continue

            stacks = []

            for member_name in (
                "all_stacks",
                "stacks",
            ):
                member = getattr(
                    texture_set,
                    member_name,
                    None,
                )

                try:
                    value = (
                        member()
                        if callable(member)
                        else member
                    )
                except Exception:
                    value = None

                if value is not None:
                    try:
                        stacks.extend(
                            list(value)
                        )
                    except TypeError:
                        pass

            if stacks:
                try:
                    substance_painter.textureset.set_active_stack(
                        stacks[0]
                    )
                    return True
                except Exception:
                    traceback.print_exc()

            return False

        return False

    def folder_preview_output_path(
        self,
        folder_path: str,
    ) -> Optional[str]:
        cache_root = self.preview_cache_dir()

        if not cache_root:
            return None

        preview_directory = os.path.join(
            cache_root,
            "_FolderPreviews",
        )
        os.makedirs(
            preview_directory,
            exist_ok=True,
        )

        safe_name = self.normalize_folder_path(
            folder_path
        ).replace(
            "/",
            "__",
        )

        for invalid_character in '<>:"/\\|?*':
            safe_name = safe_name.replace(
                invalid_character,
                "_",
            )

        if not safe_name:
            safe_name = "Project"

        return os.path.join(
            preview_directory,
            safe_name + "_Preview.png",
        )

    def create_folder_preview(
        self,
        folder_path: str,
    ):
        """Manually capture the current 3D viewport for one folder."""
        if not substance_painter.project.is_open():
            self.status_label.setText(
                "Open and save a Painter project first."
            )
            return

        output_path = self.folder_preview_output_path(
            folder_path
        )

        if not output_path:
            self.status_label.setText(
                "Save the SPP project before creating a preview."
            )
            return

        # Select the matching set first. Painter has no public API for
        # automatically isolating it, so the screenshot uses the current
        # visibility and camera state of the 3D viewport.
        self.activate_texture_set_for_folder(
            folder_path
        )

        self.status_label.setText(
            "Creating folder preview from the current 3D viewport..."
        )

        QtCore.QTimer.singleShot(
            350,
            lambda: self.capture_folder_preview(
                folder_path,
                output_path,
            ),
        )

    def capture_widget_with_winapi(
        self,
        widget: QtWidgets.QWidget,
    ) -> Optional[QtGui.QImage]:
        """Capture the visible widget pixels using Windows BitBlt.

        Qt QWidget.grab() returns black for Painter's GPU-rendered viewport.
        BitBlt copies the already rendered pixels from the Windows desktop.
        """
        if os.name != "nt":
            return None

        try:
            hwnd = int(widget.winId())
        except Exception:
            traceback.print_exc()
            return None

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        rect = wintypes.RECT()

        if not user32.GetWindowRect(
            wintypes.HWND(hwnd),
            ctypes.byref(rect),
        ):
            return None

        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)

        if width <= 1 or height <= 1:
            return None

        screen_dc = user32.GetDC(None)

        if not screen_dc:
            return None

        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(
            screen_dc,
            width,
            height,
        )

        if not memory_dc or not bitmap:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
            return None

        old_object = gdi32.SelectObject(
            memory_dc,
            bitmap,
        )

        SRCCOPY = 0x00CC0020
        CAPTUREBLT = 0x40000000

        copied = gdi32.BitBlt(
            memory_dc,
            0,
            0,
            width,
            height,
            screen_dc,
            rect.left,
            rect.top,
            SRCCOPY | CAPTUREBLT,
        )

        image = None

        if copied:
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [
                    ("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3),
                ]

            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(
                BITMAPINFOHEADER
            )
            bitmap_info.bmiHeader.biWidth = width
            # Negative height requests a top-down bitmap.
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = 0

            byte_count = width * height * 4
            pixel_buffer = ctypes.create_string_buffer(
                byte_count
            )

            DIB_RGB_COLORS = 0

            rows = gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                height,
                pixel_buffer,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
            )

            if rows:
                qt_image = QtGui.QImage(
                    pixel_buffer.raw,
                    width,
                    height,
                    width * 4,
                    QtGui.QImage.Format.Format_ARGB32,
                )
                # Detach from the temporary ctypes buffer.
                image = qt_image.copy()

        gdi32.SelectObject(
            memory_dc,
            old_object,
        )
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)

        return image

    def capture_folder_preview(
        self,
        folder_path: str,
        output_path: str,
    ):
        viewport = self.find_3d_viewport()

        if viewport is None:
            self.status_label.setText(
                "The visible 3D Viewport was not found."
            )
            return

        screenshot = self.capture_widget_with_winapi(
            viewport
        )

        if screenshot is None or screenshot.isNull():
            self.status_label.setText(
                "Could not capture the 3D Viewport with Windows."
            )
            return

        side = min(
            screenshot.width(),
            screenshot.height(),
        )
        crop_rect = QtCore.QRect(
            (screenshot.width() - side) // 2,
            (screenshot.height() - side) // 2,
            side,
            side,
        )

        square = screenshot.copy(
            crop_rect
        )
        preview = square.scaled(
            512,
            512,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

        if not preview.save(
            output_path,
            "PNG",
        ):
            self.status_label.setText(
                "Could not save the folder preview to disk."
            )
            return

        self._data.setdefault(
            "folder_previews",
            {},
        )[
            self.normalize_folder_path(folder_path)
        ] = os.path.normpath(output_path)

        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText(
            "Folder preview created from the visible 3D Viewport. "
            "It changes only when Create Preview is used again."
        )

    def remove_folder_preview(
        self,
        folder_path: str,
    ):
        previews = self._data.setdefault(
            "folder_previews",
            {},
        )
        normalized_folder = self.normalize_folder_path(
            folder_path
        )
        preview_path = previews.pop(
            normalized_folder,
            None,
        )

        if (
            preview_path
            and os.path.isfile(
                str(preview_path)
            )
        ):
            try:
                os.remove(
                    str(preview_path)
                )
            except OSError:
                traceback.print_exc()

        self.save_data()
        self.populate_asset_tiles()
        self.status_label.setText(
            "Folder preview removed."
        )

    def rename_folder_path(
        self,
        old_path: str,
    ):
        if not old_path:
            return

        old_name = old_path.split("/")[-1]
        parent_path = "/".join(
            old_path.split("/")[:-1]
        )

        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Folder",
            "New name:",
            text=old_name,
        )

        if not accepted:
            return

        new_name = (
            new_name.strip()
            .replace("/", "_")
            .replace("\\", "_")
        )

        if not new_name or new_name == old_name:
            return

        new_path = (
            new_name
            if not parent_path
            else parent_path + "/" + new_name
        )

        folders = self._data.get(
            "folders",
            [],
        )

        if new_path in folders:
            QtWidgets.QMessageBox.information(
                self,
                "Rename Folder",
                "A folder with this name already exists.",
            )
            return

        updated_folders = []

        for folder in folders:
            if folder == old_path:
                updated_folders.append(new_path)

            elif folder.startswith(old_path + "/"):
                updated_folders.append(
                    new_path + folder[len(old_path):]
                )

            else:
                updated_folders.append(folder)

        self._data["folders"] = updated_folders

        for record in self._data.get(
            "resources",
            {},
        ).values():
            record_folder = record.get(
                "folder",
                "",
            )

            if record_folder == old_path:
                record["folder"] = new_path

            elif record_folder.startswith(
                old_path + "/"
            ):
                record["folder"] = (
                    new_path
                    + record_folder[len(old_path):]
                )

        self.save_data()
        self.populate_asset_tiles()

    def delete_folder_path(
        self,
        folder_path: str,
    ):
        if not folder_path:
            return

        result = QtWidgets.QMessageBox.question(
            self,
            "Delete Folder",
            (
                f"Delete folder '{folder_path}'?\n\n"
                "Textures inside it will be moved to "
                "the current parent folder."
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )

        if result != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        parent_path = "/".join(
            folder_path.split("/")[:-1]
        )

        self._data["folders"] = [
            folder
            for folder in self._data.get(
                "folders",
                [],
            )
            if (
                folder != folder_path
                and not folder.startswith(
                    folder_path + "/"
                )
            )
        ]

        folder_previews = self._data.setdefault(
            "folder_previews",
            {},
        )

        for preview_folder in list(folder_previews):
            if (
                preview_folder == folder_path
                or preview_folder.startswith(
                    folder_path + "/"
                )
            ):
                preview_path = folder_previews.pop(
                    preview_folder
                )

                if (
                    preview_path
                    and os.path.isfile(
                        str(preview_path)
                    )
                ):
                    try:
                        os.remove(
                            str(preview_path)
                        )
                    except OSError:
                        traceback.print_exc()

        for record in self._data.get(
            "resources",
            {},
        ).values():
            record_folder = record.get(
                "folder",
                "",
            )

            if (
                record_folder == folder_path
                or record_folder.startswith(
                    folder_path + "/"
                )
            ):
                record["folder"] = parent_path

        self.save_data()
        self.populate_asset_tiles()

    def move_items_to_folder(
        self,
        items: list[QtWidgets.QListWidgetItem],
        folder_path: str,
    ):
        moved = 0

        for item in items:
            if item.data(ROLE_KIND) != KIND_RESOURCE:
                continue

            url = item.data(
                ROLE_RESOURCE_URL
            )
            record = self._data.get(
                "resources",
                {},
            ).get(url)

            if record is None:
                continue

            record["folder"] = folder_path
            moved += 1

        if moved:
            self.save_data()
            self.populate_asset_tiles()
            self.status_label.setText(
                f"Moved {moved} texture(s) to "
                f"{folder_path.split('/')[-1]}"
            )

    def rename_asset_alias(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        url = item.data(ROLE_RESOURCE_URL)
        record = self._data.get("resources", {}).get(url)

        if record is None:
            return

        current_name = record.get(
            "alias",
            record.get("original_name", "Resource"),
        )

        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Alias",
            (
                "Custom display name:\n\n"
                "Painter's real ResourceID cannot be renamed "
                "through the public Python API."
            ),
            text=current_name,
        )

        if not accepted:
            return

        new_name = new_name.strip()

        if not new_name:
            return

        record["alias"] = new_name

        self.save_data()
        self.populate_asset_tiles()

    def reset_asset_alias(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        url = item.data(ROLE_RESOURCE_URL)
        record = self._data.get("resources", {}).get(url)

        if record is None:
            return

        record["alias"] = record.get(
            "original_name",
            "Resource",
        )

        self.save_data()
        self.populate_asset_tiles()

    def move_asset_to_folder(
        self,
        item: QtWidgets.QListWidgetItem,
        folder_path: str,
    ):
        url = item.data(ROLE_RESOURCE_URL)
        record = self._data.get("resources", {}).get(url)

        if record is None:
            return

        record["folder"] = folder_path

        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText(
            f"Moved to: {folder_path}"
        )

    def delete_asset_file_and_record(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        """Compatibility wrapper for deleting one texture."""
        url = item.data(
            ROLE_RESOURCE_URL
        )

        if not url:
            return

        self.delete_assets_files_and_records(
            [url]
        )

    def delete_assets_files_and_records(
        self,
        resource_urls: list[str],
    ):
        """Delete all selected texture files and their manager records."""
        resources = self._data.setdefault(
            "resources",
            {},
        )
        unique_urls = [
            url
            for url in dict.fromkeys(
                resource_urls
            )
            if url in resources
        ]

        if not unique_urls:
            return

        delete_entries = []

        for url in unique_urls:
            record = resources.get(
                url,
                {},
            )
            file_path = record.get(
                "preview_path",
                "",
            )
            display_name = record.get(
                "alias",
                record.get(
                    "original_name",
                    "Texture",
                ),
            )

            delete_entries.append(
                {
                    "url": url,
                    "record": record,
                    "file_path": (
                        os.path.normpath(
                            str(file_path)
                        )
                        if file_path
                        else ""
                    ),
                    "display_name": str(
                        display_name
                    ),
                }
            )

        count = len(delete_entries)

        if count == 1:
            title = "Delete Texture"
            message = (
                f'Delete "{delete_entries[0]["display_name"]}" '
                "from the Custom Asset Manager?"
            )
        else:
            title = "Delete Textures"
            message = (
                f"Delete {count} selected textures from "
                "the Custom Asset Manager?"
            )

        preview_names = [
            entry["display_name"]
            for entry in delete_entries[:10]
        ]

        if count > 1:
            message += (
                "\n\n"
                + "\n".join(
                    "• " + name
                    for name in preview_names
                )
            )

            if count > len(preview_names):
                message += (
                    f"\n• …and "
                    f"{count - len(preview_names)} more"
                )

        existing_file_count = sum(
            1
            for entry in delete_entries
            if (
                entry["file_path"]
                and os.path.isfile(
                    entry["file_path"]
                )
            )
        )

        if existing_file_count:
            message += (
                "\n\nThe corresponding image file"
                + (
                    "s"
                    if existing_file_count != 1
                    else ""
                )
                + " will also be permanently deleted from disk."
            )

        message += (
            "\n\nPainter does not provide a public API for deleting "
            "resources from its native Assets panel. Those resources may "
            "remain there, but they will stay hidden in this manager."
        )

        answer = QtWidgets.QMessageBox.warning(
            self,
            title,
            message,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )

        if (
            answer
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return

        hidden_urls = set(
            self._data.setdefault(
                "hidden_resource_urls",
                [],
            )
        )
        manually_deleted_urls = set(
            self._data.setdefault(
                "manually_deleted_resource_urls",
                [],
            )
        )

        deleted_count = 0
        failed_entries = []

        for entry in delete_entries:
            url = entry["url"]
            file_path = entry[
                "file_path"
            ]

            if (
                file_path
                and os.path.isfile(file_path)
            ):
                try:
                    os.remove(
                        file_path
                    )
                except OSError:
                    traceback.print_exc()
                    failed_entries.append(
                        entry
                    )
                    continue

            hidden_urls.add(url)
            manually_deleted_urls.add(
                url
            )
            resources.pop(
                url,
                None,
            )
            deleted_count += 1

        self._data[
            "hidden_resource_urls"
        ] = sorted(hidden_urls)
        self._data[
            "manually_deleted_resource_urls"
        ] = sorted(
            manually_deleted_urls
        )

        self._preview_cache.clear()
        self.save_data()
        self.populate_asset_tiles()

        if failed_entries:
            failed_names = "\n".join(
                "• " + entry[
                    "display_name"
                ]
                for entry in failed_entries[:10]
            )

            if (
                len(failed_entries) > 10
            ):
                failed_names += (
                    f"\n• …and "
                    f"{len(failed_entries) - 10} more"
                )

            QtWidgets.QMessageBox.warning(
                self,
                "Some Textures Were Not Deleted",
                (
                    "These files could not be deleted from disk "
                    "and remain in the manager:\n\n"
                    + failed_names
                ),
            )

        self.status_label.setText(
            f"Deleted {deleted_count} texture(s)"
            + (
                f"; {len(failed_entries)} failed."
                if failed_entries
                else ". Refresh will not restore them; "
                "a generated bake map can return only after a new bake."
            )
        )

    def rename_exported_file(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        """Rename the bitmap and relink every layer that uses it."""
        url = item.data(
            ROLE_RESOURCE_URL
        )
        record = self._data.get(
            "resources",
            {},
        ).get(url)

        if record is None:
            return

        old_path = record.get(
            "preview_path"
        )

        if (
            not old_path
            or not os.path.isfile(
                str(old_path)
            )
        ):
            QtWidgets.QMessageBox.information(
                self,
                "Rename Exported File",
                "The exported file does not exist on disk.",
            )
            return

        old_path = os.path.normpath(
            str(old_path)
        )
        old_stem = os.path.splitext(
            os.path.basename(old_path)
        )[0]

        new_stem, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Exported File",
            "New file name:",
            text=old_stem,
        )

        if not accepted:
            return

        new_stem = str(
            new_stem
        ).strip()

        if not new_stem:
            return

        for invalid_character in '<>:"/\\|?*':
            new_stem = new_stem.replace(
                invalid_character,
                "_",
            )

        if new_stem == old_stem:
            return

        success, new_url, renamed_old_path, new_path = (
            self.rename_resource_file_stem(
                url,
                new_stem,
            )
        )

        if not success:
            if (
                new_path
                and os.path.exists(
                    new_path
                )
            ):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Rename Exported File",
                    "A file with that name already exists.",
                )
            else:
                self.status_label.setText(
                    "Could not rename the exported file."
                )

            return

        self.update_marmoset_manifest_file_path(
            renamed_old_path,
            new_path,
        )

        self._preview_cache.clear()
        self.save_data()
        self.populate_asset_tiles()

        relinked_count = int(
            record.get(
                "relinked_layer_sources",
                0,
            )
            or 0
        )

        self.status_label.setText(
            f"Renamed: {os.path.basename(new_path)}"
            + (
                f"; relinked {relinked_count} layer source(s)."
                if relinked_count
                else "."
            )
        )

    # ------------------------------------------------------------------
    # Previews
    # ------------------------------------------------------------------

    def set_asset_preview(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        url = item.data(ROLE_RESOURCE_URL)
        record = self._data.get("resources", {}).get(url)

        if record is None:
            return

        start_dir = ""
        existing = record.get("preview_path")

        if existing and os.path.isfile(existing):
            start_dir = os.path.dirname(existing)

        filter_string = (
            "Images ("
            + " ".join("*" + ext for ext in PREVIEW_EXTENSIONS)
            + ");;All files (*)"
        )

        path, _selected = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Preview Image",
            start_dir,
            filter_string,
        )

        if not path:
            return

        record["preview_path"] = os.path.normpath(path)

        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText(
            f"Preview set: {os.path.basename(path)}"
        )

    def clear_asset_preview(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        url = item.data(ROLE_RESOURCE_URL)
        record = self._data.get("resources", {}).get(url)

        if record is None:
            return

        record.pop("preview_path", None)

        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText("Preview cleared.")

    def auto_link_previews_from_folder(self):
        """Match image files in a folder to resources by name."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select a folder containing texture images",
        )

        if not directory:
            return

        # Build a lookup of normalized file stem -> full path.
        files_by_key: dict[str, str] = {}

        try:
            entries = os.listdir(directory)
        except OSError:
            traceback.print_exc()
            self.status_label.setText("Could not read that folder.")
            return

        for entry in entries:
            full_path = os.path.join(directory, entry)

            if not os.path.isfile(full_path):
                continue

            stem, extension = os.path.splitext(entry)

            if extension.lower() not in PREVIEW_EXTENSIONS:
                continue

            files_by_key[self.normalize_match_key(stem)] = full_path

        if not files_by_key:
            self.status_label.setText(
                "No supported images found in that folder."
            )
            return

        resources = self._data.get("resources", {})
        matched = 0

        for record in resources.values():
            candidates = [
                record.get("original_name", ""),
                record.get("alias", ""),
            ]

            match_path = None

            for candidate in candidates:
                key = self.normalize_match_key(candidate)

                if not key:
                    continue

                # Exact key match first, then containment either way.
                if key in files_by_key:
                    match_path = files_by_key[key]
                    break

                for file_key, file_path in files_by_key.items():
                    if key in file_key or file_key in key:
                        match_path = file_path
                        break

                if match_path:
                    break

            if match_path:
                record["preview_path"] = os.path.normpath(match_path)
                matched += 1

        self.save_data()
        self.populate_asset_tiles()

        self.status_label.setText(
            f"Linked previews for {matched} resource(s)."
        )

    @staticmethod
    def normalize_match_key(name: str) -> str:
        """Lowercase and strip everything but alphanumerics for fuzzy matching."""
        return "".join(
            char
            for char in str(name).lower()
            if char.isalnum()
        )

    def preview_cache_dir(self) -> Optional[str]:
        """Return a Bakes folder next to the saved SPP project."""
        if not substance_painter.project.is_open():
            return None

        project_path = substance_painter.project.file_path()

        if not project_path:
            return None

        project_directory = os.path.dirname(str(project_path))
        project_name = os.path.splitext(
            os.path.basename(str(project_path))
        )[0]

        return os.path.join(
            project_directory,
            project_name + "_Bakes",
        )

    @staticmethod
    def safe_disk_folder_name(
        value: str,
    ) -> str:
        safe_name = str(
            value
        ).strip()

        for invalid_character in '<>:"/\\|?*':
            safe_name = safe_name.replace(
                invalid_character,
                "_",
            )

        safe_name = safe_name.rstrip(
            ". "
        )

        return safe_name or "Texture_Set"

    def texture_set_disk_directory(
        self,
        texture_set_name: str,
    ) -> Optional[str]:
        cache_dir = self.preview_cache_dir()

        if not cache_dir:
            return None

        return os.path.join(
            cache_dir,
            self.safe_disk_folder_name(
                texture_set_name
            ),
        )

    def move_generated_texture_with_relink(
        self,
        resource_url: str,
        record: dict[str, Any],
        old_path: str,
        new_path: str,
    ) -> tuple[bool, str]:
        """Move one generated texture and preserve all Fill Layer bindings."""
        old_path = os.path.normpath(
            str(old_path)
        )
        new_path = os.path.normpath(
            str(new_path)
        )

        if (
            os.path.normcase(
                os.path.abspath(old_path)
            )
            == os.path.normcase(
                os.path.abspath(new_path)
            )
        ):
            return False, resource_url

        texture_set_name = str(
            record.get(
                "texture_set_name",
                "",
            )
        ).strip()

        if not texture_set_name:
            manager_folder = str(
                record.get(
                    "folder",
                    "",
                )
            ).replace(
                "\\",
                "/",
            )
            texture_set_name = (
                manager_folder.split(
                    "/",
                    1,
                )[0]
                if manager_folder
                else ""
            )

        old_stem = os.path.splitext(
            os.path.basename(old_path)
        )[0]
        new_stem = os.path.splitext(
            os.path.basename(new_path)
        )[0]
        candidate_names = {
            self.normalized_resource_name(
                old_stem
            ),
            self.normalized_resource_name(
                new_stem
            ),
        }
        candidate_urls = (
            self.project_resource_urls_for_record(
                record,
                candidate_names,
            )
        )
        pending_bindings = (
            self.source_bindings_for_resources(
                texture_set_name or None,
                candidate_urls,
                candidate_names,
            )
        )

        try:
            os.makedirs(
                os.path.dirname(new_path),
                exist_ok=True,
            )

            if os.path.isfile(new_path):
                os.remove(new_path)

            os.replace(
                old_path,
                new_path,
            )

        except OSError:
            traceback.print_exc()
            return False, resource_url

        record["preview_path"] = new_path
        record["exported_file_name"] = (
            os.path.basename(new_path)
        )

        if pending_bindings:
            try:
                new_resource_id = (
                    self.import_texture_resource(
                        new_path
                    )
                )
                replaced = (
                    self.replace_layer_source_bindings(
                        pending_bindings,
                        new_resource_id,
                    )
                )

                if replaced:
                    painter_urls = list(
                        record.get(
                            "painter_resource_urls",
                            [],
                        )
                    )
                    new_painter_url = (
                        new_resource_id.url()
                    )

                    if (
                        new_painter_url
                        not in painter_urls
                    ):
                        painter_urls.append(
                            new_painter_url
                        )

                    record[
                        "painter_resource_urls"
                    ] = painter_urls
                    record[
                        "last_relinked_resource_url"
                    ] = new_painter_url
                    record[
                        "relinked_layer_sources"
                    ] = replaced

            except Exception:
                traceback.print_exc()

        new_resource_url = resource_url

        if str(resource_url).startswith(
            "bakesetup+"
        ):
            new_resource_url = (
                self.bake_setup_resource_url(
                    new_path
                )
            )

        return True, new_resource_url

    def organize_generated_files_on_disk(
        self,
    ) -> int:
        """Mirror Bake Manager's Texture Set folders on disk.

        Only generated Painter/Bake Setup maps are moved. Service files,
        imported user textures and the Marmoset bridge workspace are left
        untouched.
        """
        cache_dir = self.preview_cache_dir()

        if (
            not cache_dir
            or not os.path.isdir(cache_dir)
        ):
            return 0

        resources = self._data.setdefault(
            "resources",
            {},
        )
        hidden_urls = set(
            self._data.setdefault(
                "hidden_resource_urls",
                [],
            )
        )
        deleted_urls = set(
            self._data.setdefault(
                "manually_deleted_resource_urls",
                [],
            )
        )
        moved_count = 0

        for resource_url, record in list(
            resources.items()
        ):
            source = str(
                record.get(
                    "source",
                    "",
                )
            )

            # Marmoset keeps its own manifest/work directory and must not be
            # rearranged by the Painter-file organizer.
            if source == "Marmoset Toolbag 5":
                continue

            texture_set_name = str(
                record.get(
                    "texture_set_name",
                    "",
                )
            ).strip()

            if (
                source != "Bake Manager Setup"
                and not texture_set_name
            ):
                continue

            old_path = record.get(
                "preview_path",
                "",
            )

            if (
                not old_path
                or not os.path.isfile(
                    str(old_path)
                )
            ):
                continue

            old_path = os.path.normpath(
                str(old_path)
            )

            try:
                inside_bakes_root = (
                    os.path.commonpath(
                        (
                            os.path.abspath(old_path),
                            os.path.abspath(cache_dir),
                        )
                    )
                    == os.path.abspath(cache_dir)
                )
            except ValueError:
                inside_bakes_root = False

            if not inside_bakes_root:
                continue

            if not texture_set_name:
                manager_folder = str(
                    record.get(
                        "folder",
                        "",
                    )
                ).replace(
                    "\\",
                    "/",
                )
                texture_set_name = (
                    manager_folder.split(
                        "/",
                        1,
                    )[0]
                    if manager_folder
                    else ""
                )

            if not texture_set_name:
                continue

            target_directory = (
                self.texture_set_disk_directory(
                    texture_set_name
                )
            )

            if not target_directory:
                continue

            new_path = os.path.join(
                target_directory,
                os.path.basename(old_path),
            )

            moved, new_resource_url = (
                self.move_generated_texture_with_relink(
                    resource_url,
                    record,
                    old_path,
                    new_path,
                )
            )

            if not moved:
                continue

            if new_resource_url != resource_url:
                resources.pop(
                    resource_url,
                    None,
                )
                resources[
                    new_resource_url
                ] = record

                if resource_url in hidden_urls:
                    hidden_urls.discard(
                        resource_url
                    )
                    hidden_urls.add(
                        new_resource_url
                    )

                if resource_url in deleted_urls:
                    deleted_urls.discard(
                        resource_url
                    )
                    deleted_urls.add(
                        new_resource_url
                    )

            moved_count += 1

        self._data[
            "hidden_resource_urls"
        ] = sorted(hidden_urls)
        self._data[
            "manually_deleted_resource_urls"
        ] = sorted(deleted_urls)

        if moved_count:
            self._preview_cache.clear()

        return moved_count

    def texture_set_folder_path(
        self,
        texture_set_name: str,
    ) -> str:
        """Return/create a Texture Set folder directly under Project."""
        safe_name = str(
            texture_set_name
        ).strip()

        for invalid_character in '<>:"/\\|?*':
            safe_name = safe_name.replace(
                invalid_character,
                "_",
            )

        safe_name = safe_name.rstrip(". ")

        if not safe_name:
            safe_name = "Texture_Set"

        folder_path = self.normalize_folder_path(
            safe_name
        )

        folders = self._data.setdefault(
            "folders",
            [],
        )

        if folder_path not in folders:
            folders.append(folder_path)

        return folder_path

    def generate_bake_map_previews(
        self,
        automatic: bool = False,
        delete_from_assets_after_export: bool = False,
    ):
        """Export current baked mesh maps and link only their active versions."""
        if self._auto_export_running:
            return

        self._auto_export_running = True

        def finish():
            self._auto_export_running = False
        if not substance_painter.project.is_open():
            QtWidgets.QMessageBox.information(
                self,
                "Bake Manager",
                "Open a Substance Painter project first.",
            )
            finish()
            return

        cache_dir = self.preview_cache_dir()

        if not cache_dir:
            self.status_label.setText(
                "Save the project first, then generate previews."
            )
            finish()
            return

        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            traceback.print_exc()
            self.status_label.setText(
                "Could not create the preview cache folder."
            )
            finish()
            return

        # A regular Refresh must respect files deleted through this manager.
        # Painter may reuse the same ResourceID after a real rebake, therefore
        # deleted mesh maps are restored only for an automatic bake cycle.
        try:
            active_mesh_map_urls = {
                entry[2]
                for entry in self.collect_mesh_map_signature()
            }

            hidden_urls = set(
                self._data.setdefault(
                    "hidden_resource_urls",
                    [],
                )
            )
            manually_deleted_urls = set(
                self._data.setdefault(
                    "manually_deleted_resource_urls",
                    [],
                )
            )

            if automatic:
                # check_for_new_bakes() calls this mode only after Painter
                # completed a busy/bake cycle or changed Mesh Map ResourceIDs.
                restore_urls = active_mesh_map_urls & hidden_urls

                if restore_urls:
                    hidden_urls.difference_update(
                        restore_urls
                    )
                    manually_deleted_urls.difference_update(
                        restore_urls
                    )

                    self._data["hidden_resource_urls"] = sorted(
                        hidden_urls
                    )
                    self._data[
                        "manually_deleted_resource_urls"
                    ] = sorted(
                        manually_deleted_urls
                    )

            self.synchronize_project_resources()

        except Exception:
            traceback.print_exc()

        # Map every baked mesh map by *name* -> (texture set, usage name).
        # Matching by name (not full URL) avoids the version-hash mismatch
        # between list_project_resources() and get_mesh_map_resource().
        mesh_maps_by_name: dict[str, tuple[str, str]] = {}

        try:
            texture_sets = substance_painter.textureset.all_texture_sets()
        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not query texture sets. See Python Console."
            )
            finish()
            return

        mesh_map_usages = (
            substance_painter.textureset.MeshMapUsage.__members__.items()
        )

        for texture_set in texture_sets:
            for usage_name, usage in mesh_map_usages:
                try:
                    resource_id = texture_set.get_mesh_map_resource(usage)
                except Exception:
                    continue

                if resource_id is None:
                    continue

                mesh_maps_by_name[resource_id.name] = (
                    texture_set.name(),
                    usage_name,
                )

        resources = self._data.get("resources", {})

        # Link the freshly exported file only to the currently active
        # ResourceID version. Previous bake versions may already point to
        # renamed archive files and must not be overwritten or duplicated.
        active_project_urls = {
            resource_id.url()
            for resource_id
            in substance_painter.resource.list_project_resources()
            if str(resource_id.context).startswith("project")
        }

        targets: dict[str, tuple[str, str]] = {}

        for url, record in resources.items():
            if url not in active_project_urls:
                continue

            try:
                name = (
                    substance_painter.resource.ResourceID.from_url(url).name
                )
            except Exception:
                name = record.get("original_name", "")

            info = mesh_maps_by_name.get(name)

            if info is not None:
                targets[url] = info

        print(
            "[BakeManager] mesh maps found:",
            len(mesh_maps_by_name),
            "| tracked mesh-map targets:",
            len(targets),
        )

        if not targets:
            self.status_label.setText(
                "No baked mesh maps found among tracked resources."
            )
            finish()
            return

        exported = self.export_mesh_map_previews(
            substance_painter.export,
            cache_dir,
            targets,
        )

        if not exported:
            self.status_label.setText(
                "Mesh map export produced no files. See Python Console."
            )
            finish()
            return

        matched = 0

        created_texture_set_folders = set()

        for url, (texture_set_name, usage_name) in targets.items():
            path = exported.get((url, usage_name))

            if path and os.path.isfile(path):
                normalized_path = os.path.normpath(path)
                record = resources[url]
                old_preview_path = record.get("preview_path")

                record["preview_path"] = normalized_path
                record["exported_file_name"] = os.path.basename(
                    normalized_path
                )

                # Automatically organize every freshly baked map into the
                # folder belonging to its Painter Texture Set.
                texture_set_folder = self.texture_set_folder_path(
                    texture_set_name
                )
                record["folder"] = texture_set_folder
                record["texture_set_name"] = texture_set_name

                created_texture_set_folders.add(
                    texture_set_folder
                )

                current_alias = record.get(
                    "alias",
                    record.get("original_name", ""),
                )

                new_alias = os.path.splitext(
                    os.path.basename(normalized_path)
                )[0]
                file_suffix = MESH_MAP_FILE_SUFFIXES.get(
                    usage_name,
                    usage_name,
                )

                legacy_auto_aliases = {
                    texture_set_name + "_Bake_" + usage_name,
                    texture_set_name + "_Bake_" + file_suffix,
                }

                # Preserve names renamed manually by the user, but migrate
                # aliases generated automatically by older plugin versions.
                if (
                    current_alias == record.get("original_name", "")
                    or current_alias in legacy_auto_aliases
                ):
                    record["alias"] = new_alias

                # Remove the obsolete automatically generated _Bake_ file
                # after its replacement has been written successfully.
                if (
                    old_preview_path
                    and os.path.normcase(str(old_preview_path))
                    != os.path.normcase(normalized_path)
                    and os.path.isfile(str(old_preview_path))
                ):
                    old_stem = os.path.splitext(
                        os.path.basename(str(old_preview_path))
                    )[0]

                    if old_stem in legacy_auto_aliases:
                        try:
                            os.remove(str(old_preview_path))
                        except OSError:
                            traceback.print_exc()

                matched += 1

        self._preview_cache.clear()
        self.save_data()
        self.populate_asset_tiles()

        if (
            delete_from_assets_after_export
            and matched > 0
        ):
            resource_urls_to_delete = [
                url
                for url in targets
                if url in active_project_urls
            ]

            self.status_label.setText(
                f"Saved {matched} bake map(s). "
                "Removing their project copies from Assets..."
            )

            # Allow Painter to finish updating the Assets model after export.
            QtCore.QTimer.singleShot(
                700,
                lambda urls=resource_urls_to_delete: (
                    self.delete_resource_urls_from_painter_assets(
                        urls
                    )
                ),
            )
        else:
            folder_count = len(
                created_texture_set_folders
            )

            self.status_label.setText(
                (
                    f"Saved {matched} bake map(s) into "
                    f"{folder_count} Texture Set folder(s)."
                    if automatic
                    else
                    f"Generated {matched} preview(s) and organized them "
                    f"into {folder_count} Texture Set folder(s)."
                )
            )

        finish()

    def export_mesh_map_previews(
        self,
        export_module,
        cache_dir: str,
        targets: dict[str, tuple[str, str]],
    ) -> dict[tuple[str, str], str]:
        """Export the requested mesh maps as small PNGs.

        Returns a mapping of (resource_url, usage_name) -> exported file path.
        """
        # Group the usages we need per texture set.
        usages_by_set: dict[str, set[str]] = {}

        for url, (texture_set_name, usage_name) in targets.items():
            usages_by_set.setdefault(texture_set_name, set()).add(usage_name)

        # Build one export map per usage. File names are made deterministic so
        # we can match the resulting files back to each resource afterwards.
        seen_usages: set[str] = set()

        for usages in usages_by_set.values():
            seen_usages.update(usages)

        export_maps = []

        for usage_name in sorted(seen_usages):
            src_map_name = MESH_MAP_EXPORT_NAMES.get(usage_name)
            file_suffix = MESH_MAP_FILE_SUFFIXES.get(usage_name)

            if not src_map_name or not file_suffix:
                continue

            export_maps.append(
                {
                    "fileName": "$textureSet_" + file_suffix,
                    "channels": [
                        {
                            "destChannel": channel,
                            "srcChannel": channel,
                            "srcMapType": "meshMap",
                            "srcMapName": src_map_name,
                            "srcPath": "",
                        }
                        for channel in ("R", "G", "B")
                    ],
                    "parameters": {
                        "fileFormat": "png",
                        # Preserve smooth gradients and reduce visible
                        # quantization/banding in normal and height maps.
                        "bitDepth": "16",
                        "dithering": False,
                    },
                }
            )

        if not export_maps:
            return {}

        temporary_export_dir = os.path.join(
            cache_dir,
            "_PainterExportTemp",
        )

        try:
            if os.path.isdir(
                temporary_export_dir
            ):
                shutil.rmtree(
                    temporary_export_dir
                )

            os.makedirs(
                temporary_export_dir,
                exist_ok=True,
            )
        except OSError:
            traceback.print_exc()
            return {}

        export_config = {
            "exportShaderParams": False,
            "exportPath": temporary_export_dir,
            "defaultExportPreset": "BakeManagerBakes",
            "exportPresets": [
                {
                    "name": "BakeManagerBakes",
                    "maps": export_maps,
                }
            ],
            "exportList": [
                {"rootPath": texture_set_name}
                for texture_set_name in usages_by_set
            ],
            "exportParameters": [
                {
                    "parameters": {
                        "paddingAlgorithm": "passthrough",
                    }
                }
            ],
        }

        try:
            result = export_module.export_project_textures(export_config)
        except Exception:
            traceback.print_exc()
            return {}

        print(
            "[BakeManager] export status:",
            result.status,
            "| message:",
            result.message,
        )

        # result.textures is keyed by (Texture Set name, stack name).
        # Use the texture set from the key (reliable) and the usage token from
        # the file name (our deterministic "CAMpreview_<set>_<usage>" pattern).
        files_by_set: dict[str, list[str]] = {}

        for (set_name, _stack_name), file_list in result.textures.items():
            target_directory = (
                self.texture_set_disk_directory(
                    set_name
                )
            )

            if not target_directory:
                continue

            try:
                os.makedirs(
                    target_directory,
                    exist_ok=True,
                )
            except OSError:
                traceback.print_exc()
                continue

            for exported_path in file_list:
                exported_path = os.path.normpath(
                    str(exported_path)
                )

                if not os.path.isfile(
                    exported_path
                ):
                    continue

                organized_path = os.path.join(
                    target_directory,
                    os.path.basename(
                        exported_path
                    ),
                )

                try:
                    if os.path.isfile(
                        organized_path
                    ):
                        os.remove(
                            organized_path
                        )

                    os.replace(
                        exported_path,
                        organized_path,
                    )
                    files_by_set.setdefault(
                        set_name,
                        [],
                    ).append(
                        organized_path
                    )

                except OSError:
                    traceback.print_exc()

        try:
            if os.path.isdir(
                temporary_export_dir
            ):
                shutil.rmtree(
                    temporary_export_dir
                )
        except OSError:
            traceback.print_exc()

        total_files = sum(
            len(value)
            for value in files_by_set.values()
        )
        print(
            "[BakeManager] files organized by Texture Set:",
            total_files,
        )

        exported: dict[tuple[str, str], str] = {}

        for url, (texture_set_name, usage_name) in targets.items():
            file_suffix = MESH_MAP_FILE_SUFFIXES.get(usage_name)

            if not file_suffix:
                continue

            expected_stem = texture_set_name + "_" + file_suffix

            for file_path in files_by_set.get(texture_set_name, []):
                file_stem = os.path.splitext(
                    os.path.basename(file_path)
                )[0]

                if file_stem == expected_stem:
                    exported[(url, usage_name)] = file_path
                    break

        print("[BakeManager] previews matched:", len(exported))

        return exported

    # ------------------------------------------------------------------
    # Native Painter Assets cleanup
    # ------------------------------------------------------------------

    def resource_objects_from_urls(
        self,
        resource_urls: list[str],
    ) -> list[Any]:
        """Resolve live Resource objects for exact project ResourceIDs."""
        result = []

        for url in resource_urls:
            try:
                resource_id = (
                    substance_painter.resource.ResourceID.from_url(
                        url
                    )
                )
                retrieved = (
                    substance_painter.resource.Resource.retrieve(
                        resource_id
                    )
                )

                if retrieved:
                    result.append(retrieved[0])
                    continue
            except Exception:
                pass

            # Fallback: exact URL match among search results.
            try:
                resource_id = (
                    substance_painter.resource.ResourceID.from_url(
                        url
                    )
                )
                candidates = (
                    substance_painter.resource.search(
                        resource_id.name
                    )
                )
            except Exception:
                candidates = []

            for candidate in candidates:
                try:
                    if candidate.identifier().url() == url:
                        result.append(candidate)
                        break
                except Exception:
                    continue

        return result

    @staticmethod
    def find_assets_item_view():
        """Find a currently valid visible item view in Painter's Assets dock."""
        assets_docks = []

        for widget in QtWidgets.QApplication.allWidgets():
            if not isinstance(
                widget,
                QtWidgets.QDockWidget,
            ):
                continue

            try:
                title = (
                    widget.windowTitle()
                    .strip()
                    .lower()
                )
            except RuntimeError:
                # The Python wrapper outlived the underlying C++ widget.
                continue

            if title == "assets":
                assets_docks.append(
                    widget
                )

        candidates = []

        for dock in assets_docks:
            try:
                views = dock.findChildren(
                    QtWidgets.QAbstractItemView
                )
            except RuntimeError:
                continue

            for view in views:
                try:
                    if not view.isVisible():
                        continue

                    area = (
                        view.width()
                        * view.height()
                    )
                except RuntimeError:
                    # Painter rebuilt the Assets panel while we were scanning.
                    continue

                candidates.append(
                    (
                        area,
                        view,
                    )
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda pair: pair[0],
            reverse=True,
        )
        return candidates[0][1]

    def trigger_assets_delete_menu_action(self):
        """Trigger the visible native Assets context-menu Delete action."""
        delete_action = None
        visible_menus = []

        for widget in QtWidgets.QApplication.topLevelWidgets():
            if not isinstance(widget, QtWidgets.QMenu):
                continue

            try:
                if widget.isVisible():
                    visible_menus.append(widget)
            except RuntimeError:
                continue

        for menu in visible_menus:
            for action in menu.actions():
                try:
                    action_text = (
                        action.text()
                        .replace("&", "")
                        .strip()
                        .lower()
                    )
                except RuntimeError:
                    continue

                if action_text == "delete":
                    delete_action = action
                    break

            if delete_action is not None:
                break

        if delete_action is None:
            for menu in visible_menus:
                try:
                    menu.close()
                except RuntimeError:
                    pass

            self.status_label.setText(
                "Bake maps were saved, but Painter's native "
                "Assets Delete command was not found."
            )
            return

        try:
            delete_action.trigger()
        except RuntimeError:
            traceback.print_exc()
            self.status_label.setText(
                "Painter's Assets Delete command could not be triggered."
            )
            return

        self.status_label.setText(
            "Bake maps saved to disk and removed from Painter Assets."
        )

        QtCore.QTimer.singleShot(
            700,
            self.refresh_resources,
        )

    def send_delete_key_to_assets(
        self,
        attempt: int = 0,
    ):
        """Open Painter's native Assets context menu and trigger Delete.

        Painter may rebuild the Assets QListView asynchronously. In that case
        the Python wrapper can still exist after the C++ widget was deleted.
        Re-find the view and retry quietly instead of printing a traceback.
        """
        view = self.find_assets_item_view()

        if view is None:
            if attempt < 5:
                QtCore.QTimer.singleShot(
                    160,
                    lambda: self.send_delete_key_to_assets(
                        attempt + 1
                    ),
                )
                return

            self.status_label.setText(
                "Bake maps were saved, but the Assets panel "
                "was not available for automatic cleanup."
            )
            return

        try:
            selection_model = view.selectionModel()
            selected_indexes = (
                selection_model.selectedIndexes()
                if selection_model is not None
                else []
            )

            if not selected_indexes:
                current_index = view.currentIndex()

                if current_index.isValid():
                    selected_indexes = [
                        current_index
                    ]

            if not selected_indexes:
                if attempt < 5:
                    QtCore.QTimer.singleShot(
                        160,
                        lambda: self.send_delete_key_to_assets(
                            attempt + 1
                        ),
                    )
                    return

                self.status_label.setText(
                    "Bake maps were saved, but Painter did not select "
                    "their tiles in Assets."
                )
                return

            index = selected_indexes[0]
            item_rect = view.visualRect(
                index
            )

            if not item_rect.isValid():
                if attempt < 5:
                    QtCore.QTimer.singleShot(
                        160,
                        lambda: self.send_delete_key_to_assets(
                            attempt + 1
                        ),
                    )
                    return

                self.status_label.setText(
                    "Bake maps were saved, but the selected Assets tile "
                    "is not currently visible."
                )
                return

            viewport = view.viewport()
            local_position = item_rect.center()
            global_position = viewport.mapToGlobal(
                local_position
            )

            view.setFocus(
                QtCore.Qt.FocusReason.OtherFocusReason
            )
            view.setCurrentIndex(
                index
            )

            press_event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseButtonPress,
                QtCore.QPointF(
                    local_position
                ),
                QtCore.QPointF(
                    global_position
                ),
                QtCore.Qt.MouseButton.RightButton,
                QtCore.Qt.MouseButton.RightButton,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
            release_event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseButtonRelease,
                QtCore.QPointF(
                    local_position
                ),
                QtCore.QPointF(
                    global_position
                ),
                QtCore.Qt.MouseButton.RightButton,
                QtCore.Qt.MouseButton.NoButton,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )

            QtWidgets.QApplication.sendEvent(
                viewport,
                press_event,
            )
            QtWidgets.QApplication.sendEvent(
                viewport,
                release_event,
            )

            context_event = QtGui.QContextMenuEvent(
                QtGui.QContextMenuEvent.Reason.Mouse,
                local_position,
                global_position,
            )

            QtWidgets.QApplication.postEvent(
                viewport,
                context_event,
            )

            QtCore.QTimer.singleShot(
                250,
                self.trigger_assets_delete_menu_action,
            )

        except RuntimeError:
            # The Assets panel was rebuilt between lookup and use.
            if attempt < 5:
                QtCore.QTimer.singleShot(
                    160,
                    lambda: self.send_delete_key_to_assets(
                        attempt + 1
                    ),
                )
                return

            self.status_label.setText(
                "Bake maps were saved, but Painter rebuilt the Assets "
                "panel before automatic cleanup finished."
            )

        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Bake maps were saved, but automatic Assets cleanup failed."
            )

    def delete_resource_urls_from_painter_assets(
        self,
        resource_urls: list[str],
    ):
        """Select exact baked resources and delete them from Project Assets."""
        resource_objects = self.resource_objects_from_urls(
            resource_urls
        )

        if not resource_objects:
            self.status_label.setText(
                "Bake maps were saved, but no live Painter resources "
                "were found to remove from Assets."
            )
            return

        try:
            # show_resources_in_ui requires Resource objects, not ResourceID.
            substance_painter.resource.show_resources_in_ui(
                resource_objects
            )
        except Exception:
            traceback.print_exc()
            self.status_label.setText(
                "Could not select baked resources in Painter Assets."
            )
            return

        # The Assets view updates selection asynchronously.
        QtCore.QTimer.singleShot(
            350,
            self.send_delete_key_to_assets,
        )

    # ------------------------------------------------------------------
    # Automatic bake export watcher
    # ------------------------------------------------------------------

    def collect_mesh_map_signature(self) -> tuple:
        if not substance_painter.project.is_open():
            return tuple()

        signature = []

        try:
            texture_sets = substance_painter.textureset.all_texture_sets()
            usage_items = (
                substance_painter.textureset.MeshMapUsage.__members__.items()
            )
        except Exception:
            return tuple()

        for texture_set in texture_sets:
            try:
                texture_set_name = texture_set.name()
            except Exception:
                texture_set_name = str(texture_set)

            for usage_name, usage in usage_items:
                try:
                    resource_id = texture_set.get_mesh_map_resource(usage)
                except Exception:
                    continue

                if resource_id is None:
                    continue

                try:
                    resource_url = resource_id.url()
                except Exception:
                    resource_url = str(resource_id)

                signature.append(
                    (
                        texture_set_name,
                        usage_name,
                        resource_url,
                    )
                )

        return tuple(sorted(signature))

    def current_bakes_need_export(
        self,
        signature: tuple,
    ) -> bool:
        """Return True when a current Mesh Map has no usable disk-backed tile."""
        if not signature:
            return False

        resources = self._data.get(
            "resources",
            {},
        )

        for _texture_set_name, _usage_name, resource_url in signature:
            record = resources.get(
                resource_url
            )

            if record is None:
                return True

            preview_path = record.get(
                "preview_path"
            )

            if (
                not preview_path
                or not os.path.isfile(
                    str(preview_path)
                )
            ):
                return True

        return False

    def initialize_bake_watcher(self):
        if not substance_painter.project.is_open():
            return

        try:
            if substance_painter.project.is_busy():
                return
        except Exception:
            pass

        signature = self.collect_mesh_map_signature()
        self._last_mesh_map_signature = signature

        # Existing missing files are respected as intentionally deleted.
        # Export happens only after an actual Painter bake/busy cycle or when
        # the Mesh Map ResourceID signature changes.

    def check_for_new_bakes(self):
        """Watch project loading and export only after a real Painter bake."""
        if self._auto_export_running or self._bake_setup_running:
            return

        if not substance_painter.project.is_open():
            self._last_mesh_map_signature = None
            self._painter_was_busy = False

            if self._loaded_project_data_path is not None:
                self._loaded_project_data_path = None
                self._data = self.default_data()
                self._current_folder_path = ""
                self.asset_list.clear()
                self.breadcrumb_label.setText("Project")
                self.status_label.setText(
                    "Open a project to restore its Asset Manager data."
                )

            return

        current_data_path = self.normalized_data_path(
            self.project_data_path()
        )

        # Painter often initializes plugins before the SPP is fully opened.
        # As soon as the project path becomes available, load its JSON sidecar.
        if (
            current_data_path is not None
            and current_data_path
            != self._loaded_project_data_path
        ):
            self.load_manager()
            self.initialize_bake_watcher()
            return

        if current_data_path is None:
            # ProjectEditionEntered may occur before a file path exists.
            # Ensure rows from the previous scene can never remain visible.
            if (
                self._loaded_project_data_path is not None
                or self._data.get("resources")
                or any(
                    project.get("setups")
                    for project in self._data.get(
                        "bake_manager",
                        {},
                    ).get(
                        "projects",
                        {},
                    ).values()
                )
            ):
                self.reset_new_unsaved_project_state()
            else:
                self.status_label.setText(
                    "New project: create a Bake Setup from scratch, "
                    "then save the Painter project."
                )

            return

        self.import_marmoset_manifest()

        try:
            project_is_busy = bool(
                substance_painter.project.is_busy()
            )
        except Exception:
            project_is_busy = False

        if project_is_busy:
            self._painter_was_busy = True
            return

        signature = self.collect_mesh_map_signature()

        if not signature:
            return

        if self._last_mesh_map_signature is None:
            self._last_mesh_map_signature = signature
            self._painter_was_busy = False
            return

        signature_changed = (
            signature != self._last_mesh_map_signature
        )
        completed_busy_cycle = self._painter_was_busy

        self._painter_was_busy = False

        if not signature_changed and not completed_busy_cycle:
            # A PNG may have been deleted manually from the manager or disk.
            # Do not recreate it until Painter performs another bake.
            return

        self._last_mesh_map_signature = signature

        QtCore.QTimer.singleShot(
            1000,
            lambda: self.generate_bake_map_previews(
                automatic=True,
                delete_from_assets_after_export=True,
            ),
        )


    # ------------------------------------------------------------------
    # Painter UI integration
    # ------------------------------------------------------------------

    def on_asset_double_clicked(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        if item.data(ROLE_KIND) == KIND_FOLDER:
            self.open_folder(
                item.data(ROLE_FOLDER_PATH) or ""
            )
            return

        self.show_resource_in_painter(item)

    def show_resource_in_painter(
        self,
        item: QtWidgets.QListWidgetItem,
    ):
        url = item.data(ROLE_RESOURCE_URL)

        if not url:
            return

        try:
            target_id = (
                substance_painter.resource.ResourceID.from_url(
                    url
                )
            )

            target_resource = None

            # First try exact retrieval from the ResourceID. Painter 11.1.3
            # returns a list of Resource objects here.
            try:
                retrieved = (
                    substance_painter.resource.Resource.retrieve(
                        target_id
                    )
                )

                if retrieved:
                    target_resource = retrieved[0]
            except Exception:
                target_resource = None

            # Fallback to search and exact URL comparison.
            if target_resource is None:
                try:
                    search_results = (
                        substance_painter.resource.search(
                            target_id.name
                        )
                    )
                except Exception:
                    search_results = []

                for resource_object in search_results:
                    try:
                        candidate_id = (
                            resource_object.identifier()
                        )

                        if candidate_id.url() == url:
                            target_resource = resource_object
                            break

                    except Exception:
                        continue

            if target_resource is None:
                # Archived bake versions can still exist as valid PNG files
                # even though their old Painter ResourceID has disappeared.
                record = self._data.get(
                    "resources",
                    {},
                ).get(
                    url,
                    {},
                )
                preview_path = record.get(
                    "preview_path"
                )

                if (
                    preview_path
                    and os.path.isfile(
                        str(preview_path)
                    )
                ):
                    self.status_label.setText(
                        "This is an archived disk file. "
                        "It is no longer a live Painter resource, "
                        "but drag-and-drop still works."
                    )
                    return

                self.status_label.setText(
                    "Painter resource is no longer available."
                )
                return

            # Both functions require Resource, not ResourceID.
            try:
                target_resource.show_in_ui()
            except Exception:
                substance_painter.resource.show_resources_in_ui(
                    [target_resource]
                )

            self.status_label.setText(
                f"Shown in Painter Assets: {item.text()}"
            )

        except Exception:
            traceback.print_exc()

            self.status_label.setText(
                "Painter could not select this resource."
            )


def _updater_settings():
    return QtCore.QSettings(
        "BakeManager",
        "Updater",
    )


def _normalized_version(value: Any) -> str:
    text = str(value or "").strip()
    return text[1:] if text.lower().startswith("v") else text


def _version_key(value: Any) -> tuple[int, ...]:
    text = _normalized_version(value)
    match = re.match(r"^(\d+(?:\.\d+)*)", text)

    if match is None:
        return ()

    return tuple(
        int(part)
        for part in match.group(1).split(".")
    )


def _read_limited_response(response, maximum_bytes: int) -> bytes:
    length_header = response.headers.get("Content-Length")

    if length_header:
        try:
            if int(length_header) > maximum_bytes:
                raise RuntimeError("The update download is unexpectedly large.")
        except ValueError:
            pass

    chunks = []
    received = 0

    while True:
        chunk = response.read(1024 * 1024)

        if not chunk:
            break

        received += len(chunk)

        if received > maximum_bytes:
            raise RuntimeError("The update download is unexpectedly large.")

        chunks.append(chunk)

    return b"".join(chunks)


def _github_request_with_curl(
    url: str,
    maximum_bytes: int,
    timeout: int,
    original_error: Exception,
) -> bytes:
    """Use Windows curl when Painter is denied direct socket access."""
    curl_path = shutil.which("curl.exe")

    if not curl_path:
        raise RuntimeError(
            "Could not connect to GitHub: "
            + str(getattr(original_error, "reason", original_error))
            + ". Windows curl.exe was not found for the fallback request."
        )

    file_descriptor, output_path = tempfile.mkstemp(
        prefix="BakeManager-download-",
        suffix=".tmp",
    )
    os.close(file_descriptor)

    command = [
        curl_path,
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--max-redirs",
        "5",
        "--connect-timeout",
        str(max(1, timeout)),
        "--max-time",
        str(max(1, timeout)),
        "--max-filesize",
        str(maximum_bytes),
        "--header",
        "Accept: application/vnd.github+json",
        "--header",
        "User-Agent: BakeManager/" + PLUGIN_VERSION,
        "--header",
        "X-GitHub-Api-Version: 2022-11-28",
        "--output",
        output_path,
        url,
    ]

    try:
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout + 10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("The GitHub request timed out.")

        if completed.returncode != 0:
            details = completed.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            details = details[-500:] if details else "curl failed"
            if completed.returncode == 22 and "404" in details:
                raise RuntimeError(
                    "No published Bake Manager release was found."
                )

            raise RuntimeError(
                "Could not connect to GitHub through the Windows fallback: "
                + details
            )

        size = os.path.getsize(output_path)

        if size > maximum_bytes:
            raise RuntimeError("The update download is unexpectedly large.")

        with open(output_path, "rb") as stream:
            return stream.read()

    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass

def _github_request(url: str, maximum_bytes: int, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BakeManager/" + PLUGIN_VERSION,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _read_limited_response(response, maximum_bytes)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RuntimeError("No published Bake Manager release was found.")
        raise RuntimeError(
            "GitHub returned HTTP " + str(error.code) + "."
        )
    except urllib.error.URLError as error:
        if os.name == "nt":
            return _github_request_with_curl(
                url,
                maximum_bytes,
                timeout,
                error,
            )

        raise RuntimeError(
            "Could not connect to GitHub: " + str(error.reason)
        )


def _fetch_latest_release() -> dict[str, Any]:
    raw_data = _github_request(
        UPDATE_API_URL,
        2 * 1024 * 1024,
        15,
    )
    payload = json.loads(raw_data.decode("utf-8"))

    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an invalid release description.")

    tag_name = str(payload.get("tag_name") or "")
    version = _normalized_version(tag_name)

    if not _version_key(version):
        raise RuntimeError("The latest GitHub release has no valid version tag.")

    selected_asset = None

    for asset in payload.get("assets") or []:
        if (
            isinstance(asset, dict)
            and str(asset.get("name") or "") == UPDATE_ASSET_NAME
        ):
            selected_asset = asset
            break

    return {
        "version": version,
        "tag_name": tag_name,
        "name": str(payload.get("name") or tag_name),
        "notes": str(payload.get("body") or "No release notes were provided."),
        "release_url": str(payload.get("html_url") or ""),
        "asset_url": str(
            (selected_asset or {}).get("browser_download_url") or ""
        ),
        "asset_size": int((selected_asset or {}).get("size") or 0),
    }


def _safe_relative_update_path(value: Any) -> str:
    relative = str(value or "").replace("\\", "/").strip("/")
    parts = [part for part in relative.split("/") if part]

    if (
        not parts
        or any(part in (".", "..") for part in parts)
        or ":" in parts[0]
    ):
        raise RuntimeError("Unsafe path in the update package: " + relative)

    return "/".join(parts)


def _is_protected_user_file(relative_path: str) -> bool:
    name = os.path.basename(relative_path).lower()
    return (
        name == "ui_state.json"
        or name == "bake_templates.json"
        or name.startswith("bakeproject__")
        or name.endswith(".spsm")
        or name.endswith(".bak")
        or name == ".ignore_assets_pt"
    )


def _extract_update_archive(archive_path: str, destination: str):
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = archive.infolist()

        if len(members) > 5000:
            raise RuntimeError("The update archive contains too many files.")

        total_size = sum(member.file_size for member in members)

        if total_size > UPDATE_MAX_ARCHIVE_BYTES * 2:
            raise RuntimeError("The extracted update is unexpectedly large.")

        destination_root = os.path.abspath(destination)

        for member in members:
            relative = _safe_relative_update_path(member.filename)
            target = os.path.abspath(
                os.path.join(destination_root, *relative.split("/"))
            )

            if os.path.commonpath((destination_root, target)) != destination_root:
                raise RuntimeError("The update archive contains an unsafe path.")

            unix_mode = (member.external_attr >> 16) & 0o170000

            if unix_mode == 0o120000:
                raise RuntimeError("Symbolic links are not allowed in updates.")

            if member.is_dir():
                os.makedirs(target, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target), exist_ok=True)

            with archive.open(member, "r") as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)


def _find_update_package_root(extracted_root: str) -> str:
    candidates = []

    for current_root, directories, files in os.walk(extracted_root):
        depth = len(Path(current_root).relative_to(extracted_root).parts)

        if depth > 3:
            directories[:] = []
            continue

        if "__init__.py" in files and "bake_manager.py" in files:
            candidates.append(current_root)

    if not candidates:
        raise RuntimeError(
            "BakeManager.zip does not contain a valid BakeManager folder."
        )

    candidates.sort(
        key=lambda path: (
            os.path.basename(path).lower() != "bakemanager",
            len(Path(path).relative_to(extracted_root).parts),
        )
    )
    return candidates[0]


def _managed_update_files(package_root: str) -> list[str]:
    manifest_path = os.path.join(package_root, "update_manifest.json")
    managed_files = list(UPDATE_MANAGED_FILES)

    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as stream:
            manifest = json.load(stream)

        if not isinstance(manifest, dict) or not isinstance(
            manifest.get("files"), list
        ):
            raise RuntimeError("update_manifest.json is invalid.")

        managed_files = [
            _safe_relative_update_path(item)
            for item in manifest["files"]
        ]

    required = {"__init__.py", "bake_manager.py"}

    if not required.issubset(set(managed_files)):
        raise RuntimeError("The update manifest omits required plugin files.")

    result = []

    for relative in managed_files:
        relative = _safe_relative_update_path(relative)

        if _is_protected_user_file(relative):
            raise RuntimeError(
                "The update tried to replace protected user data: " + relative
            )

        source = os.path.join(package_root, *relative.split("/"))

        if not os.path.isfile(source):
            if relative in required:
                raise RuntimeError("The update is missing " + relative + ".")
            continue

        result.append(relative)

    return result


def _verify_downloaded_version(package_root: str, expected_version: str):
    source_path = os.path.join(package_root, "bake_manager.py")

    with open(source_path, "r", encoding="utf-8") as stream:
        source = stream.read(256 * 1024)

    match = re.search(
        r'^PLUGIN_VERSION\s*=\s*["\']([^"\']+)["\']',
        source,
        flags=re.MULTILINE,
    )

    if match is None:
        raise RuntimeError("The downloaded plugin does not declare its version.")

    if _normalized_version(match.group(1)) != _normalized_version(expected_version):
        raise RuntimeError(
            "The downloaded plugin version does not match the GitHub release."
        )


def _install_update(release: dict[str, Any]) -> dict[str, Any]:
    asset_url = str(release.get("asset_url") or "")

    if not asset_url.startswith("https://github.com/"):
        raise RuntimeError(
            "This release has no trusted " + UPDATE_ASSET_NAME + " asset."
        )

    advertised_size = int(release.get("asset_size") or 0)

    if advertised_size > UPDATE_MAX_ARCHIVE_BYTES:
        raise RuntimeError("The release archive is unexpectedly large.")

    work_directory = tempfile.mkdtemp(prefix="BakeManager-update-")
    archive_path = os.path.join(work_directory, UPDATE_ASSET_NAME)
    extracted_root = os.path.join(work_directory, "extracted")
    plugin_root = os.path.dirname(os.path.abspath(__file__))
    staging_root = tempfile.mkdtemp(prefix=".update-stage-", dir=plugin_root)
    backup_root = tempfile.mkdtemp(prefix=".update-backup-", dir=plugin_root)
    installed = []

    try:
        archive_data = _github_request(
            asset_url,
            UPDATE_MAX_ARCHIVE_BYTES,
            60,
        )

        with open(archive_path, "wb") as stream:
            stream.write(archive_data)

        os.makedirs(extracted_root, exist_ok=True)
        _extract_update_archive(archive_path, extracted_root)
        package_root = _find_update_package_root(extracted_root)
        _verify_downloaded_version(package_root, str(release["version"]))
        managed_files = _managed_update_files(package_root)

        for relative in managed_files:
            source = os.path.join(package_root, *relative.split("/"))
            staged = os.path.join(staging_root, *relative.split("/"))
            os.makedirs(os.path.dirname(staged), exist_ok=True)
            shutil.copy2(source, staged)

        for relative in managed_files:
            target = os.path.join(plugin_root, *relative.split("/"))
            staged = os.path.join(staging_root, *relative.split("/"))
            backup = os.path.join(backup_root, *relative.split("/"))
            existed = os.path.isfile(target)

            if existed:
                os.makedirs(os.path.dirname(backup), exist_ok=True)
                shutil.copy2(target, backup)

            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(staged, target)
            installed.append((relative, existed))

        return {
            "version": str(release["version"]),
            "files": [relative for relative, _existed in installed],
        }

    except Exception:
        for relative, existed in reversed(installed):
            target = os.path.join(plugin_root, *relative.split("/"))
            backup = os.path.join(backup_root, *relative.split("/"))

            try:
                if existed and os.path.isfile(backup):
                    shutil.copy2(backup, target)
                elif not existed and os.path.isfile(target):
                    os.remove(target)
            except Exception:
                traceback.print_exc()

        raise

    finally:
        shutil.rmtree(work_directory, ignore_errors=True)
        shutil.rmtree(staging_root, ignore_errors=True)
        shutil.rmtree(backup_root, ignore_errors=True)


class BakeManagerUpdateThread(QtCore.QThread):
    completed = QtCore.Signal(str, object)
    failed = QtCore.Signal(str, str)

    def __init__(self, operation: str, release=None, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.release = release

    def run(self):
        try:
            if self.operation == "check":
                result = _fetch_latest_release()
            elif self.operation == "install":
                result = _install_update(self.release or {})
            else:
                raise RuntimeError("Unknown updater operation.")

            self.completed.emit(self.operation, result)
        except Exception as error:
            if self.operation != "check":
                traceback.print_exc()
            self.failed.emit(self.operation, str(error))


class BakeManagerUpdateDialog(QtWidgets.QDialog):
    UPDATE = 1
    LATER = 2
    SKIP = 3

    def __init__(self, release: dict[str, Any], parent=None):
        super().__init__(parent)
        self.choice = self.LATER
        self.setWindowTitle("Bake Manager update available")
        self.setWindowIcon(create_plugin_icon())
        self.setModal(True)
        self.resize(620, 460)

        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(
            "Installed version: "
            + PLUGIN_VERSION
            + ". Available version: "
            + str(release["version"])
            + "."
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        notes_label = QtWidgets.QLabel("What changed:")
        layout.addWidget(notes_label)

        notes = QtWidgets.QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(str(release.get("notes") or ""))
        layout.addWidget(notes, 1)

        buttons = QtWidgets.QDialogButtonBox()
        update_button = buttons.addButton(
            "Update",
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        later_button = buttons.addButton(
            "Later",
            QtWidgets.QDialogButtonBox.ButtonRole.RejectRole,
        )
        skip_button = buttons.addButton(
            "Skip This Version",
            QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        update_button.setDefault(True)
        update_button.clicked.connect(lambda: self._finish(self.UPDATE))
        later_button.clicked.connect(lambda: self._finish(self.LATER))
        skip_button.clicked.connect(lambda: self._finish(self.SKIP))
        layout.addWidget(buttons)

    def _finish(self, choice: int):
        self.choice = choice
        self.accept()

    def reject(self):
        self.choice = self.LATER
        super().reject()


class BakeManagerUpdateController(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._progress = None
        self._closing = False

    def start_check(self):
        if self._closing or self._thread is not None:
            return

        settings = _updater_settings()
        deferred_until = float(settings.value("deferred_until", 0) or 0)

        if deferred_until > time.time():
            return

        self._start_thread("check")

    def _start_thread(self, operation: str, release=None):
        thread = BakeManagerUpdateThread(operation, release, self)
        self._thread = thread
        thread.completed.connect(self._on_completed)
        thread.failed.connect(self._on_failed)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def _on_thread_finished(self):
        thread = self._thread
        self._thread = None

        if thread is not None:
            thread.deleteLater()

    def _on_completed(self, operation: str, result: object):
        if self._closing:
            return

        if operation == "check":
            self._handle_release(dict(result))
        elif operation == "install":
            self._finish_progress()
            self._handle_install_success(dict(result))

    def _on_failed(self, operation: str, message: str):
        if self._closing:
            return

        if operation == "check":
            if message == "No published Bake Manager release was found.":
                return

            print("[BakeManager] Update check failed: " + message)
            return

        self._finish_progress()
        QtWidgets.QMessageBox.critical(
            self._dialog_parent(),
            "Bake Manager update failed",
            message
            + "\n\nThe updater attempted to restore the previous files. "
            + "You can try again later.",
        )

    def _handle_release(self, release: dict[str, Any]):
        latest = _version_key(release.get("version"))
        current = _version_key(PLUGIN_VERSION)

        if not latest or latest <= current:
            return

        settings = _updater_settings()
        if _normalized_version(settings.value("installed_version", "")) == str(
            release["version"]
        ):
            return


        if _normalized_version(settings.value("skipped_version", "")) == str(
            release["version"]
        ):
            return

        dialog = BakeManagerUpdateDialog(release, self._dialog_parent())
        dialog.exec()

        if dialog.choice == BakeManagerUpdateDialog.SKIP:
            settings.setValue("skipped_version", release["version"])
            settings.remove("deferred_until")
            settings.sync()
            return

        if dialog.choice == BakeManagerUpdateDialog.LATER:
            settings.setValue(
                "deferred_until",
                time.time() + UPDATE_DEFER_SECONDS,
            )
            settings.sync()
            return

        settings.remove("deferred_until")
        settings.sync()

        if not release.get("asset_url"):
            QtWidgets.QMessageBox.warning(
                self._dialog_parent(),
                "Update archive not found",
                "The release does not contain the required file "
                + UPDATE_ASSET_NAME
                + ".",
            )
            return

        self._progress = QtWidgets.QProgressDialog(
            "Downloading and installing Bake Manager "
            + str(release["version"])
            + "...",
            "",
            0,
            0,
            self._dialog_parent(),
        )
        self._progress.setWindowTitle("Bake Manager Update")
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.show()
        self._start_thread("install", release)

    def _finish_progress(self):
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _handle_install_success(self, result: dict[str, Any]):
        settings = _updater_settings()
        settings.setValue("installed_version", result.get("version", ""))
        settings.remove("skipped_version")
        settings.remove("deferred_until")
        settings.sync()

        message_box = QtWidgets.QMessageBox(self._dialog_parent())
        message_box.setWindowTitle("Bake Manager Updated")
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
        message_box.setText(
            "Update "
            + str(result.get("version") or "")
            + " was installed successfully."
        )
        message_box.setInformativeText(
            "Restart Substance 3D Painter to load the new version."
        )
        restart_button = message_box.addButton(
            "Restart Painter",
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        message_box.addButton(
            "Later",
            QtWidgets.QMessageBox.ButtonRole.RejectRole,
        )
        message_box.setDefaultButton(restart_button)
        message_box.exec()

        if message_box.clickedButton() is restart_button:
            self._restart_painter()

    def _restart_painter(self):
        application = QtWidgets.QApplication.instance()

        if application is None:
            return

        executable = QtCore.QCoreApplication.applicationFilePath()

        if not executable:
            executable = sys.executable

        def launch_again():
            started = QtCore.QProcess.startDetached(executable, [])
            if isinstance(started, tuple):
                started = started[0]


            if not started:
                print(
                    "[BakeManager] Painter could not be relaunched automatically."
                )

        application.aboutToQuit.connect(launch_again)
        application.quit()

    def _dialog_parent(self):
        if DOCK_WIDGET is not None:
            return DOCK_WIDGET
        return PLUGIN_WIDGET

    def shutdown(self):
        self._closing = True
        self._finish_progress()


def schedule_update_check():
    global UPDATE_CONTROLLER

    if UPDATE_CONTROLLER is None:
        UPDATE_CONTROLLER = BakeManagerUpdateController()

    QtCore.QTimer.singleShot(
        UPDATE_CHECK_DELAY_MS,
        UPDATE_CONTROLLER.start_check,
    )

def create_plugin_icon() -> QtGui.QIcon:
    for file_name in (
        "Bake_Manager_Icon.png",
        "icon.png",
        "icon.svg",
    ):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            file_name,
        )

        if os.path.isfile(path):
            icon = QtGui.QIcon(path)

            if not icon.isNull():
                return icon

    return QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton
    )


def toggle_plugin_panel():
    if DOCK_WIDGET is None:
        return

    if DOCK_WIDGET.isVisible():
        DOCK_WIDGET.hide()
    else:
        show_plugin_panel()


def show_plugin_panel():
    """Show and raise the dock panel without recreating the plugin."""
    global PLUGIN_WIDGET
    global DOCK_WIDGET

    if DOCK_WIDGET is None:
        return False

    try:
        # Make sure the dock is enabled in Painter's saved layout.
        toggle_action = DOCK_WIDGET.toggleViewAction()

        if toggle_action is not None:
            toggle_action.setChecked(True)

        DOCK_WIDGET.setVisible(True)
        DOCK_WIDGET.show()
        DOCK_WIDGET.raise_()
        DOCK_WIDGET.activateWindow()

        if PLUGIN_WIDGET is not None:
            PLUGIN_WIDGET.setVisible(True)
            PLUGIN_WIDGET.show()

        return True

    except RuntimeError:
        # The Python wrapper survived Reload Plugins, but the C++ object did not.
        DOCK_WIDGET = None
        PLUGIN_WIDGET = None
        return False

    except Exception:
        traceback.print_exc()
        return False


def schedule_panel_show():
    """Retry after Painter has finished restoring its workspace/layout."""
    for delay_ms in (0, 150, 500, 1200):
        QtCore.QTimer.singleShot(
            delay_ms,
            show_plugin_panel,
        )


# ----------------------------------------------------------------------
# Plugin entry points
# ----------------------------------------------------------------------

def start_plugin():
    global PLUGIN_WIDGET
    global DOCK_WIDGET
    global TOOLBAR_BUTTON

    # Painter may call start_plugin more than once. In that case simply reopen
    # the existing dock instead of silently returning while it stays hidden.
    if PLUGIN_WIDGET is not None or DOCK_WIDGET is not None:
        if show_plugin_panel():
            schedule_panel_show()
            print("[BakeManager] Existing panel shown.")
            return

        PLUGIN_WIDGET = None
        DOCK_WIDGET = None

    try:
        PLUGIN_WIDGET = AssetManagerWidget()
        PLUGIN_WIDGET.setWindowIcon(create_plugin_icon())

        DOCK_WIDGET = substance_painter.ui.add_dock_widget(
            PLUGIN_WIDGET
        )

        try:
            DOCK_WIDGET.setWindowTitle("Bake Manager")
            DOCK_WIDGET.setWindowIcon(create_plugin_icon())
        except Exception:
            pass

        try:
            TOOLBAR_BUTTON = QtWidgets.QToolButton()
            TOOLBAR_BUTTON.setIcon(create_plugin_icon())
            TOOLBAR_BUTTON.setToolTip("Bake Manager")
            TOOLBAR_BUTTON.setAutoRaise(True)
            TOOLBAR_BUTTON.clicked.connect(toggle_plugin_panel)
            substance_painter.ui.add_plugins_toolbar_widget(
                TOOLBAR_BUTTON
            )
        except Exception:
            traceback.print_exc()
            TOOLBAR_BUTTON = None

        # A saved Painter workspace can initially create the dock as hidden.
        # Showing it again after layout restoration fixes that reliably.
        schedule_panel_show()
        schedule_update_check()

        print(
            "[BakeManager] Plugin started and panel scheduled to show."
        )

    except Exception:
        traceback.print_exc()
        PLUGIN_WIDGET = None
        DOCK_WIDGET = None
        TOOLBAR_BUTTON = None


def close_plugin():
    global PLUGIN_WIDGET
    global DOCK_WIDGET
    global TOOLBAR_BUTTON
    global UPDATE_CONTROLLER

    try:
        if PLUGIN_WIDGET is not None:
            try:
                PLUGIN_WIDGET.save_data()
            except Exception:
                traceback.print_exc()

            try:
                PLUGIN_WIDGET._bake_watch_timer.stop()
            except Exception:
                pass

            try:
                PLUGIN_WIDGET._marmoset_status_timer.stop()
            except Exception:
                pass

            try:
                PLUGIN_WIDGET.disconnect_bake_setup_events()
            except Exception:
                pass

        if TOOLBAR_BUTTON is not None:
            try:
                substance_painter.ui.delete_ui_element(
                    TOOLBAR_BUTTON
                )
            except Exception:
                traceback.print_exc()

        if DOCK_WIDGET is not None:
            substance_painter.ui.delete_ui_element(
                DOCK_WIDGET
            )

    except Exception:
        traceback.print_exc()

    if UPDATE_CONTROLLER is not None:
        UPDATE_CONTROLLER.shutdown()
        UPDATE_CONTROLLER = None

    TOOLBAR_BUTTON = None
    DOCK_WIDGET = None
    PLUGIN_WIDGET = None

    print("[BakeManager] Plugin closed.")