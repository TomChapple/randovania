import wiiload
from PySide6 import QtWidgets, QtGui
from qasync import asyncSlot

from randovania import get_data_path
from randovania.game_connection.builder.dolphin_connector_builder import DolphinConnectorBuilder
from randovania.game_connection.builder.nintendont_connector_builder import NintendontConnectorBuilder
from randovania.game_connection.game_connection import GameConnection
from randovania.game_connection.memory_executor_choice import ConnectorBuilderChoice
from randovania.gui.lib import async_dialog
from randovania.interface_common.options import Options, InfoAlert


class GameConnectionSetup:
    use_dolphin_backend: QtGui.QAction
    use_nintendont_backend: QtGui.QAction
    connect_to_game: QtGui.QAction
    upload_nintendont_action: QtGui.QAction

    def __init__(self, parent: QtWidgets.QWidget, label: QtWidgets.QLabel,
                 connection: GameConnection, options: Options):
        self.parent = parent
        self.label = label
        self.game_connection = connection
        self.options = options

        self.game_connection.Updated.connect(self.on_game_connection_updated)
        self.on_game_connection_updated()

    def create_backend_entries(self, menu: QtWidgets.QMenu):
        def _create_check(text: str, on_triggered, default: bool | None = None):
            action = QtGui.QAction(menu)
            action.setText(text)
            action.setCheckable(True)
            if default is not None:
                action.setChecked(default)
            action.triggered.connect(on_triggered)
            return action

        self.use_dolphin_backend = _create_check("Dolphin", self.on_use_dolphin_backend)
        self.use_nintendont_backend = _create_check("", self.on_use_nintendont_backend)
        self.connect_to_game = _create_check("Connect to the game", self.on_connect_to_game, True)

        menu.addAction(self.use_dolphin_backend)
        menu.addAction(self.use_nintendont_backend)
        menu.addSeparator()
        menu.addAction(self.connect_to_game)

    def create_upload_nintendont_action(self, menu: QtWidgets.QMenu):
        self.upload_nintendont_action = QtGui.QAction(menu)
        self.upload_nintendont_action.setText("Upload Nintendont to Homebrew Channel")
        self.upload_nintendont_action.triggered.connect(self.on_upload_nintendont_action)
        menu.addAction(self.upload_nintendont_action)

    def setup_tool_button_menu(self, tool_button: QtWidgets.QToolButton):
        menu = QtWidgets.QMenu(tool_button)
        self.create_backend_entries(menu)
        menu.addSeparator()
        self.create_upload_nintendont_action(menu)

        tool_button.setText("Configure backend")
        tool_button.setMenu(menu)
        self.refresh_backend()

    def on_game_connection_updated(self):
        s = self.game_connection.pretty_current_status
        game_name = self.game_connection.current_game_name
        if game_name is not None:
            s = f"{s} ({game_name})"

        self.label.setText(s)

    def refresh_backend(self):
        connector_builder = self.game_connection.connector_builder

        self.use_dolphin_backend.setChecked(isinstance(connector_builder, DolphinConnectorBuilder))
        if isinstance(connector_builder, NintendontConnectorBuilder):
            self.use_nintendont_backend.setChecked(True)
            self.use_nintendont_backend.setText(f"Nintendont: {connector_builder.executor.ip}")
            self.upload_nintendont_action.setEnabled(True)
        else:
            self.use_nintendont_backend.setChecked(False)
            self.use_nintendont_backend.setText("Nintendont")
            self.upload_nintendont_action.setEnabled(False)

    @asyncSlot()
    async def on_use_dolphin_backend(self):
        await self.game_connection.set_connector_builder(DolphinConnectorBuilder())
        with self.options as options:
            options.game_backend = ConnectorBuilderChoice.DOLPHIN
        self.refresh_backend()

    @asyncSlot()
    async def on_use_nintendont_backend(self):
        dialog = QtWidgets.QInputDialog(self.parent)
        dialog.setModal(True)
        dialog.setWindowTitle("Enter Wii's IP")
        dialog.setLabelText("Enter the IP address of your Wii. "
                            "You can check the IP address on the pause screen of Homebrew Channel.")
        if self.options.nintendont_ip is not None:
            dialog.setTextValue(self.options.nintendont_ip)

        if await async_dialog.execute_dialog(dialog) == QtWidgets.QDialog.DialogCode.Accepted:
            new_ip = dialog.textValue()
            if new_ip != "":
                if not self.options.is_alert_displayed(InfoAlert.NINTENDONT_UNSTABLE):
                    await async_dialog.warning(self.parent, "Nintendont Limitation",
                                               "Warning: The Nintendont integration isn't perfect and is known to "
                                               "crash.")
                    self.options.mark_alert_as_displayed(InfoAlert.NINTENDONT_UNSTABLE)

                with self.options as options:
                    options.nintendont_ip = new_ip
                    options.game_backend = ConnectorBuilderChoice.NINTENDONT
                await self.game_connection.set_connector_builder(NintendontConnectorBuilder(new_ip))
        self.refresh_backend()

    @asyncSlot()
    async def on_upload_nintendont_action(self):
        nintendont_file = get_data_path().joinpath("nintendont", "boot.dol")
        if not nintendont_file.is_file():
            return await async_dialog.warning(self.parent, "Missing Nintendont",
                                              "Unable to find a Nintendont executable.")

        text = f"Uploading Nintendont to the Wii at {self.options.nintendont_ip}..."
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.NoIcon, "Uploading to Homebrew Channel",
                                    text, QtWidgets.QMessageBox.StandardButton.Ok, self.parent)
        box.button(QtWidgets.QMessageBox.StandardButton.Ok).setEnabled(False)
        box.show()

        try:
            await wiiload.upload_file(nintendont_file, [], self.options.nintendont_ip)
            box.setText("Upload finished successfully. Check your Wii for more.")
        except Exception as e:
            box.setText(f"Error uploading to Wii: {e}")
        finally:
            box.button(QtWidgets.QMessageBox.StandardButton.Ok).setEnabled(True)

    def on_connect_to_game(self):
        connect_to_game = self.connect_to_game.isChecked()
        self.game_connection.set_connection_enabled(connect_to_game)
