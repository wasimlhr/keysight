import sys
import time
from PyQt5.QtWidgets import (
    QApplication, QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QTextEdit, QWidget, QGridLayout, QInputDialog, QCheckBox,
    QDialogButtonBox, QSpacerItem, QSizePolicy, QLayout
)
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg
import pyvisa
import logging
import threading
import csv
import os
import datetime
from PIL import Image


class ClickableLabel(QLabel):
    def __init__(self, channel, *args, **kwargs):
        super(ClickableLabel, self).__init__(*args, **kwargs)
        self.channel = channel

    def mousePressEvent(self, event):
        # Emit a custom signal or call a parent method if needed
        pass  # We'll set up the correct interaction in setup_ui

    def emit_clicked(self):
        self.parent().edit_channel_name(self.channel)


class PowerSupplyControlPanel:
    def __init__(self, dialog):
        logging.basicConfig(filename='power_supply.log', level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.dialog = dialog
        self.graph_dialogs = {}
        self.update_timers = {}  # Store timers separately for each graph window
        self.last_markers = {}  # Store last markers separately for each channel
        self.dialog.setWindowTitle("Control Panel N6705B")
        self.instrument = None
        self.rm = pyvisa.ResourceManager()  # Resource manager to handle VISA instruments
        self.csv_filename = "power_supply_data.csv"
        self.initialize_csv()

        # Initialize settings for each channel
        self.channel_settings = {
            i: {
                "voltage": [],
                "current": [],
                "slew_rate": [],
                "status": False,
                "ovp_indicator": None,  # GUI element for OVP
                "ocp_indicator": None,  # GUI element for OCP
                "time": []
            } for i in range(1, 5)
        }
        self.channel_status_labels = {}
        self.num_channels = 4  # Define the number of channels
        self.selected_channels = []
        self.channel_frames = {}

        self.setup_ui()
        self.timer = QTimer(self.dialog)
        self.timer.timeout.connect(self.update_live_data)
        self.timer.start(1000)  # Update every second

        self.protection_status_timer = QTimer(self.dialog)
        self.protection_status_timer.timeout.connect(self.check_protection_statuses)
        self.protection_status_timer.start(15000)  # Check every 15 seconds

        # Thread control dictionary to manage monitoring threads
        self.thread_control = {}
        self.monitoring_threads = {}

        # Start monitoring threads for each channel
        # Monitoring threads are now started after channels are selected and instrument is connected

        # Create a CSV file to store the data
        self.csv_filename = "power_supply_data.csv"
        with open(self.csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Time", "Voltage", "Current"])  # Write header
        QTimer.singleShot(100, self.toggle_channels_button.click)

        QApplication.instance().aboutToQuit.connect(self.cleanup_on_exit)  # Connect cleanup function

    def check_protection_statuses_old(self):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        status_definitions = {
            1: "Over-voltage protection triggered",
            2: "Over-current protection triggered",
            4: "Power fail detected",
            8: "Positive power limit reached",
            16: "Over-temperature condition detected",
            32: "Negative power limit reached",
            64: "Negative over-voltage protection triggered",
            128: "Positive voltage or current limit reached",
            256: "Negative voltage or current limit reached",
            512: "Output inhibited by an external signal",
            1024: "Output is unregulated",
            2048: "Output disabled due to a protection condition on another channel",
            4096: "Oscillation detector has tripped"
        }

        for channel in self.selected_channels:
            try:
                status = int(self.instrument.query(f"STAT:QUES:COND? (@{channel})").strip())
                messages = []
                for bit_value, message in status_definitions.items():
                    if status & bit_value:
                        messages.append(message)
                        if "Over-voltage" in message or "Over-current" in message:
                            self.update_indicator_ui(channel, message, "red")

                if not messages:  # If no flags are set, assume normal operation
                    self.update_indicator_ui(channel, "No protection events triggered.", "green")
                    self.add_to_output(f"Channel {channel} status: Normal operation.")

            except Exception as e:
                self.add_to_output(f"Failed to check protection statuses for channel {channel}: {str(e)}")

    def check_protection_statuses(self):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        for channel in self.selected_channels:
            try:
                status = int(self.instrument.query(f"STAT:QUES:COND? (@{channel})").strip())
                self.update_protection_status_ui(channel, status)
            except Exception as e:
                self.add_to_output(f"Failed to check protection statuses for channel {channel}: {str(e)}")

    def update_indicator_ui(self, channel, message, color):
        # This function updates the UI based on the status and the color
        # Assume there are QLabel objects to represent status and indicators
        if "Over-voltage" in message or "Over-current" in message:
            self.channel_settings[channel]['ovp_ocp_indicator'].setStyleSheet(f"background-color: {color};")
            self.channel_settings[channel]['status_label'].setText(message)

    def update_protection_status_ui(self, channel, status):
        # Initial reset of indicators to green
        self.channel_settings[channel]['ovp_indicator'].setStyleSheet("background-color: green;")
        self.channel_settings[channel]['ocp_indicator'].setStyleSheet("background-color: green;")

        # Check specific bits for OVP and OCP
        if status & 1:  # Bit for OVP
            self.channel_settings[channel]['ovp_indicator'].setStyleSheet("background-color: red;")
            self.add_to_output(f"Channel {channel} protection status updated with code: {status}")
        if status & 2:  # Bit for OCP
            self.channel_settings[channel]['ocp_indicator'].setStyleSheet("background-color: red;")

            # Log the status for debug
            self.add_to_output(f"Channel {channel} protection status updated with code: {status}")

    def close_graph(self, channel):
        if channel in self.graph_dialogs:
            self.graph_dialogs[channel].close()
            del self.graph_dialogs[channel]

    def initialize_csv(self):
        # Initialize CSV file with headers if it does not exist
        try:
            with open(self.csv_filename, 'x',
                      newline='') as file:  # 'x' mode for creating and writing; fails if file exists
                writer = csv.writer(file)
                writer.writerow(["Channel", "Time", "Voltage", "Current"])  # Writing header with channel included
        except FileExistsError:
            pass  # File already exists, headers should already be there

    def setup_ui(self):
        self.dialog_layout = QVBoxLayout(self.dialog)
        self.setup_network_controls()
        self.setup_channel_controls()  # This should create self.channel_frames
        self.load_channel_names()
        self.setup_output_window()
        self.add_custom_text()

        # Set size policy to allow resizing
        self.dialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Set minimum size
        self.dialog.setMinimumSize(650, 500)  # Adjust according to your needs

        # Load and display channel names
        self.channel_labels = {}  # Initialize this once outside the loop
        for i in range(1, 5):
            channel_key = f"CH{i}"
            # Create ClickableLabel for channel name
            channel_label = ClickableLabel(channel_key, self.dialog)
            channel_label.main_panel = self  # Set the reference to the main panel here
            channel_label.setText(self.channel_names.get(channel_key, f"Channel {i}"))
            channel_label.setStyleSheet("background-color: lightgrey; cursor: pointer;")

            # Define the mousePressEvent here to capture the label and the main_panel reference
            def on_label_click(event, label=channel_label):
                label.main_panel.edit_channel_name(label.channel)

            channel_label.mousePressEvent = on_label_click

            # Assuming channel frames are in a grid layout, add the labels to the top of each channel frame
            channel_frame_layout = self.channel_frames[i].layout()
            channel_frame_layout.insertWidget(0, channel_label)  # Insert at the top (position 0)
            self.channel_labels[channel_key] = channel_label

        # Setup resize button
        self.toggle_channels_button = QPushButton("Resize", self.dialog)
        self.toggle_channels_button.clicked.connect(self.toggle_channel_visibility)
        self.ip_button_layout.addWidget(self.toggle_channels_button)  # Add to your IP button layout

        self.dialog.resize(600, 300)  # Set initial dialog size

    def load_channel_names(self):
        self.channel_names = {}
        self.ip_address = '172.16.20.115'  # Default IP Address
        try:
            with open('module_map.txt', 'r') as file:
                for line in file:
                    if '=' in line:
                        parts = line.split('=')
                        key = parts[0].strip()
                        value = parts[1].strip()
                        if key == 'IP':
                            self.ip_address = value
                        else:
                            self.channel_names[key] = value
        except FileNotFoundError:
            pass  # Handle the case where the file does not exist

    def save_channel_names(self):
        with open('module_map.txt', 'w') as file:
            file.write(f"IP = {self.ip_address}\n")
            for channel, name in self.channel_names.items():
                file.write(f"{channel} = {name}\n")

    def edit_channel_name(self, channel):
        old_name = self.channel_names.get(channel, '')
        new_name, ok = QInputDialog.getText(self.dialog, "Edit Channel Name", "Enter new name:", QLineEdit.Normal,
                                            old_name)
        if ok and new_name:
            self.update_channel_name(channel, new_name)

    def update_channel_name(self, channel, new_name):
        # Update the channel name in the dictionary
        self.channel_names[channel] = new_name
        # Update the label in the UI
        self.channel_labels[channel].setText(new_name)
        # Write the updated mapping back to the file
        self.save_channel_names()

    def resize_main_window(self):
        # Get the size hint of the dialog
        size_hint = self.dialog.sizeHint()

        # Adjust the height of the size hint based on the preferred size of the output window
        size_hint.setHeight(size_hint.height() + self.output_window.sizeHint().height())
        self.dialog.resize(600, 320)
        if not self.channel_frames[3].isVisible() and not self.channel_frames[4].isVisible():
            # Set to the desired fixed size when channels 3 and 4 are hidden
            self.dialog.setFixedSize(500, 200)  # Replace with your desired size
        else:
            # Otherwise, allow the window to be resizable
            pass

    def toggle_channel_visibility_old(self):
        # Toggle visibility
        self.channel_frames[3].setVisible(not self.channel_frames[3].isVisible())
        self.channel_frames[4].setVisible(not self.channel_frames[4].isVisible())

        # Update layout constraints
        self.dialog_layout.setSizeConstraint(QLayout.SetMinimumSize)

        # Recalculate the layout and adjust the size of the dialog
        self.dialog_layout.invalidate()
        self.dialog_layout.activate()
        self.dialog.adjustSize()

        self.dialog.setMinimumSize(650, 300)
        self.dialog.resize(650, 600)

        # You may also want to re-enable resizing by the user if it was previously disabled
        self.dialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def toggle_channel_visibility(self):
        # Toggle visibility
        is_channel_3_visible = not self.channel_frames[3].isVisible()
        is_channel_4_visible = not self.channel_frames[4].isVisible()
        self.channel_frames[3].setVisible(is_channel_3_visible)
        self.channel_frames[4].setVisible(is_channel_4_visible)

        # If both channel 3 and 4 are now visible, set a fixed size
        if is_channel_3_visible and is_channel_4_visible:
            # Set the fixed size as desired when both channels are visible
            # self.dialog.setFixedSize(1024, 768)  # Adjust this size to your preference
            self.dialog.setMinimumSize(650, 800)  # Minimum size when channels are not visible
            self.dialog.resize(650, 900)  # Default size when channels are not visible
        else:
            # If one or both are not visible, allow the dialog to be resizable
            self.dialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.dialog.adjustSize()
            self.dialog.setMinimumSize(650, 300)  # Minimum size when channels are not visible
            self.dialog.resize(650, 600)  # Default size when channels are not visible

        # Invalidate and re-activate the layout to adjust to the changes
        self.dialog_layout.invalidate()
        self.dialog_layout.activate()

    def add_custom_text(self):
        custom_label = QLabel(self.dialog)
        custom_label.setAlignment(Qt.AlignRight)
        custom_label.setStyleSheet("font-weight: bold; font-size: 6pt;")
        custom_label.setText("<html>&copy; Achronix 2024 (abnasim) Keysight Power Supply Controller V2.01</html>")
        self.dialog_layout.addWidget(custom_label)

    def get_ip_address(self):
        dialog = QDialog(self.dialog)
        dialog.setWindowTitle("Enter IP Address and Select Active Channels")

        layout = QVBoxLayout()
        ip_label = QLabel("IP Address:")
        ip_input = QLineEdit(self.ip_address)  # Use loaded or default IP

        channel_checkboxes = {}
        channels_layout = QHBoxLayout()
        for i in range(1, 5):
            channel_checkboxes[i] = QCheckBox(f"Channel {i}")
            channels_layout.addWidget(channel_checkboxes[i])

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        layout.addWidget(ip_label)
        layout.addWidget(ip_input)
        layout.addLayout(channels_layout)
        layout.addWidget(button_box)

        dialog.setLayout(layout)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        result = dialog.exec_()
        if result == QDialog.Accepted:
            self.ip_address = ip_input.text()  # Update IP address
            selected_channels = [i for i, checkbox in channel_checkboxes.items() if checkbox.isChecked()]
            self.save_channel_names()  # Save updated IP address and channel names
            return self.ip_address, selected_channels
        else:
            return None, []

    def add_to_output(self, message):
        self.output_window.setMaximumHeight(50)  # Adjust the height value as needed
        self.output_window.setFixedSize(625, 200)  # Adjust the width and height values as needed
        self.output_window.append(message)
        # Log the message
        self.logger.info(message)

    def turn_channel_on(self, channel):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        try:
            # Command to turn on the channel
            self.instrument.write(f"OUTP ON,(@{channel})")
            time.sleep(0.5)  # Wait for the command to take effect
            # Verify the state change
            response = self.instrument.query(f"OUTP? (@{channel})").strip()
            if response == "1":
                self.add_to_output(f"Channel {channel} successfully turned on.")
                # Check if any protection mechanisms are triggered right after turning on
                self.check_protection_status(channel)
            else:
                self.add_to_output(f"Failed to turn on Channel {channel}. Current state: {response}")
        except Exception as e:
            self.add_to_output(f"Error turning on Channel {channel}: {str(e)}")

    def check_protection_status(self, channel):
        try:
            status = int(self.instrument.query(f"STAT:QUES:COND? (@{channel})").strip())
            if status != 0:
                self.update_protection_status_ui(channel, status)
        except Exception as e:
            self.add_to_output(f"Error checking protection status for Channel {channel}: {str(e)}")

    def turn_channel_off(self, channel):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        # Check current state before turning off
        current_state = self.query_channel_state(channel)
        if current_state == "OFF":
            self.add_to_output(f"Channel {channel} is already off.")
            return

        # Command to turn off the channel
        self.instrument.write(f"OUTP OFF,(@{channel})")

        # Verify the state change
        if self.query_channel_state(channel) == "OFF":
            self.add_to_output(f"Channel {channel} successfully turned off.")
            self.channel_status_labels[channel].setText(f"Channel {channel} is turned off")
            self.stop_monitoring(channel)
        else:
            self.add_to_output(f"Failed to turn off Channel {channel}")

    def query_channel_state(self, channel):
        self.add_to_output(f"Querying state for Channel {channel}")
        if self.instrument:
            try:
                # Send the query command to the instrument
                self.instrument.write(f"OUTP? (@{channel})")
                # Read the response from the instrument
                response = self.instrument.read().strip()
                # Process the response to determine the state
                if response == "0":
                    return "OFF"
                elif response == "1":
                    return "ON"
                else:
                    return "UNKNOWN"
            except Exception as e:
                print(f"Error querying channel state: {str(e)}")
                return "ERROR"
        else:
            print("Instrument is not connected.")
            return "ERROR"

    def setup_network_controls(self):
        self.ip_button_layout = QHBoxLayout()
        self.connect_button = QPushButton("Connect", self.dialog)
        self.disconnect_button = QPushButton("Disconnect", self.dialog)
        self.idn_button = QPushButton("IDN", self.dialog)
        self.rst_button = QPushButton("RST", self.dialog)
        self.fetch_button = QPushButton("Fetch", self.dialog)
        self.error_button = QPushButton("ERROR?", self.dialog)  # Button for querying errors
        self.clear_error_button = QPushButton("CLR", self.dialog)  # Button for clearing errors

        # Connect button signals to the appropriate methods
        self.fetch_button.clicked.connect(self.fetch_and_display_image)
        self.connect_button.clicked.connect(self.connect_to_instrument)
        self.disconnect_button.clicked.connect(self.disconnect_instrument)
        self.idn_button.clicked.connect(self.query_idn)
        self.rst_button.clicked.connect(self.query_rst)
        self.error_button.clicked.connect(self.query_errors)  # Method to handle error query
        self.clear_error_button.clicked.connect(self.clear_errors)  # Method to clear errors

        # Add buttons to the layout
        self.ip_button_layout.addWidget(self.connect_button)
        self.ip_button_layout.addWidget(self.disconnect_button)
        self.ip_button_layout.addWidget(self.idn_button)
        self.ip_button_layout.addWidget(self.rst_button)
        self.ip_button_layout.addWidget(self.fetch_button)
        self.ip_button_layout.addWidget(self.error_button)
        self.ip_button_layout.addWidget(self.clear_error_button)
        self.dialog_layout.addLayout(self.ip_button_layout)

    def query_errors(self):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        try:
            while True:  # Keep reading errors until the queue is empty
                error_message = self.instrument.query("SYST:ERR?").strip()
                self.add_to_output(f"Error Message: {error_message}")

                # Check if the error queue is empty
                if error_message.startswith("+0") or "+0," in error_message:
                    break  # Exit the loop if "No error" message is found
                # Optional: Add a delay to prevent flooding the communication
                time.sleep(0.1)
        except Exception as e:
            self.add_to_output(f"Error querying errors: {str(e)}")

    def clear_errors(self):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        try:
            self.instrument.write("SYST:ERR:CLE")
            self.add_to_output("Instrument errors cleared.")
        except Exception as e:
            self.add_to_output(f"Error clearing errors: {str(e)}")

    def fetch_and_display_image(self):
        try:
            self.instrument.write(':HCOPy:SDUMp:DATA:FORM GIF')
            time.sleep(2)
            self.instrument.write(':HCOPy:SDUMp:DATA?')
            time.sleep(2)

            response = bytearray()
            while True:
                chunk = self.instrument.read_raw()
                if not chunk:  # Check if chunk is empty (possibly end of data)
                    break
                response.extend(chunk)
                if b'\n' in chunk:  # Assuming newline denotes the end of the binary data
                    break

            # Remove the initial '#0' if it is part of the protocol and not part of the actual image data
            if response.startswith(b'#0'):
                response = response[2:]  # adjust the slice if more bytes need to be removed

            # Save the corrected binary data
            image_path = "instrument_display.gif"
            with open(image_path, "wb") as file:
                file.write(response)

            print("Display image has been fetched and saved.")
            self.display_image(image_path)

        except Exception as e:
            self.add_to_output(f"Error fetching/displaying image: {str(e)}")

    def display_image(self, image_path):
        image = Image.open(image_path)
        image.show()

    def add_channel_ui(self, channel):
        # Create frame and layout for this channel
        channel_frame = QFrame()
        self.channel_frames[channel] = channel_frame  # Store the frame in the channel_frames dict
        channel_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        channel_layout = QVBoxLayout(channel_frame)

        # Header label
        header_label = QLabel(f"Channel {channel}")
        header_label.setStyleSheet("font-size: 8pt; font-weight: bold;")
        channel_layout.addWidget(header_label)

        # Setup for different settings like voltage, current, and slew rate
        settings = {
            'voltage': ("Voltage, V:", "00.0 V"),
            'current': ("Current, A:", "0.0 A"),
            'slew': ("Slew Rate:", "0.0 V/s")
        }

        # Add settings to the layout
        for key, (label_text, initial_text) in settings.items():
            layout, entry, led = self.create_channel_setting(label_text, initial_text)
            channel_layout.addLayout(layout)
            self.channel_settings[channel][key + '_entry'] = entry
            self.channel_settings[channel][key + '_led'] = led

        # Indicators for OVP and OCP
        ovp_label = QLabel("OVP:")
        ovp_indicator = QLabel()
        ovp_indicator.setFixedSize(20, 20)
        ovp_indicator.setStyleSheet("background-color: green;")

        ocp_label = QLabel("OCP:")
        ocp_indicator = QLabel()
        ocp_indicator.setFixedSize(20, 20)
        ocp_indicator.setStyleSheet("background-color: green;")

        # Add buttons for setting and clearing protections
        set_ovp_button = QPushButton("Set OVP", self.dialog)
        set_ocp_button = QPushButton("Set OCP", self.dialog)
        clear_protection_button = QPushButton("CLR Limits", self.dialog)
        # Connect the buttons to their respective functions
        set_ovp_button.clicked.connect(lambda: self.set_ovp(channel))
        set_ocp_button.clicked.connect(lambda: self.set_ocp(channel))
        clear_protection_button.clicked.connect(lambda: self.clear_protection(channel))

        # Add buttons to layout
        protection_layout = QHBoxLayout()
        protection_layout.addWidget(set_ovp_button)
        protection_layout.addWidget(set_ocp_button)
        protection_layout.addWidget(clear_protection_button)
        channel_layout.addLayout(protection_layout)
        indicator_layout = QHBoxLayout()
        indicator_layout.addWidget(ovp_label)
        indicator_layout.addWidget(ovp_indicator)
        indicator_layout.addWidget(ocp_label)
        indicator_layout.addWidget(ocp_indicator)
        channel_layout.addLayout(indicator_layout)
        # Save references to OVP and OCP indicators in channel settings
        self.channel_settings[channel]['ovp_indicator'] = ovp_indicator
        self.channel_settings[channel]['ocp_indicator'] = ocp_indicator

        # Control buttons layout
        control_button_layout = QHBoxLayout()
        get_slew_button = QPushButton("Get Slew", self.dialog)
        apply_button = QPushButton(f"Apply {channel}", self.dialog)
        turn_on_button = QPushButton("Turn On", self.dialog)
        graph_button = QPushButton("Graph", self.dialog)

        # Styling for buttons
        turn_on_button.setStyleSheet("background-color: lightgreen;")
        graph_button.setEnabled(False)  # Initially disabled

        # Connect signals to slots
        get_slew_button.clicked.connect(lambda: self.get_slew_rate(channel, True))
        apply_button.clicked.connect(lambda: self.apply_settings(channel))
        turn_on_button.clicked.connect(lambda: self.toggle_channel(channel, turn_on_button, graph_button))
        graph_button.clicked.connect(lambda: self.show_live_graph(channel))

        # Add buttons to the control layout
        control_button_layout.addWidget(get_slew_button)
        control_button_layout.addWidget(apply_button)
        control_button_layout.addWidget(turn_on_button)
        control_button_layout.addWidget(graph_button)
        channel_layout.addLayout(control_button_layout)

        # Add the complete frame to the main layout
        self.channel_layout.addWidget(channel_frame, (channel - 1) // 2, (channel - 1) % 2)

        # Save references to control elements in the settings dictionary
        self.channel_settings[channel]['turn_on_button'] = turn_on_button
        self.channel_settings[channel]['graph_button'] = graph_button
        self.channel_settings[channel]['get_slew_button'] = get_slew_button
        self.channel_settings[channel]['apply_button'] = apply_button  # Save apply button reference

    def update_channel_selection(self):
        # Assuming `channel_checkboxes` is a dictionary of QCheckBox widgets keyed by channel number
        self.selected_channels = [channel for channel, checkbox in self.channel_checkboxes.items() if
                                  checkbox.isChecked()]

    def create_channel_setting(self, label_text, initial_text):
        layout = QHBoxLayout()
        label = QLabel(label_text)
        entry = QLineEdit()
        entry.setFixedWidth(100)
        led = QLabel(initial_text)
        led.setFixedSize(100, 30)
        led.setStyleSheet("background-color: black; color: lime; font-size: 16px;")

        layout.addWidget(label)
        layout.addWidget(entry)
        layout.addWidget(led)

        return layout, entry, led  # Ensure that this method returns the led correctly

    def toggle_channel(self, channel, button, graph_button):
        try:
            current_state = self.query_channel_state(channel)
            new_state = "OFF" if current_state == "ON" else "ON"
            self.instrument.write(f"OUTP {new_state},(@{channel})")

            # Verify and update GUI accordingly
            if self.query_channel_state(channel) == new_state:
                button.setText("Turn Off" if new_state == "ON" else "Turn On")
                button.setStyleSheet("background-color: red;" if new_state == "ON" else "background-color: lightgreen;")
                graph_button.setEnabled(new_state == "ON")
                self.add_to_output(f"Channel {channel} turned {new_state.lower()}.")
            else:
                self.add_to_output(f"Failed to toggle Channel {channel}.")
        except Exception as e:
            self.add_to_output(f"Error toggling channel {channel}: {str(e)}")

    def connect_to_instrument(self):
        ip_address, self.selected_channels = self.get_ip_address()
        if ip_address and self.selected_channels:  # Check if there are selected channels
            try:
                rm = pyvisa.ResourceManager()
                self.instrument = rm.open_resource(f"TCPIP::{ip_address}::INSTR")
                self.instrument.timeout = 5000
                self.selected_channels = self.selected_channels
                self.add_to_output(f"Connected to instrument. Selected channels: {self.selected_channels}")
                self.query_initial_channel_statuses()
                self.connect_button.setEnabled(False)  # Disable the connect button after connection
                self.disconnect_button.setEnabled(True)  # Enable the disconnect button after connection
            except pyvisa.VisaIOError as e:
                self.add_to_output(f"Error connecting to instrument: {e}")
                self.disconnect_button.setEnabled(False)
        else:
            self.add_to_output("Connection canceled or no channels selected.")
            self.disconnect_button.setEnabled(False)

    def disconnect_instrument(self):
        if self.instrument:
            self.instrument.close()
            self.instrument = None
            self.add_to_output("Disconnected from instrument.")
            self.connect_button.setEnabled(True)  # Enable the connect button after disconnection
            self.disconnect_button.setEnabled(False)  # Disable the disconnect button after disconnection
        else:
            self.add_to_output("Instrument is not connected.")
            self.connect_button.setEnabled(True)  # Ensure the connect button is enabled if there was no connection
            self.disconnect_button.setEnabled(False)

    def query_idn(self):
        if self.instrument:
            try:
                idn_string = self.instrument.query("*IDN?")
                self.add_to_output("IDN: " + idn_string)
            except Exception as e:
                self.add_to_output("Error querying IDN: " + str(e))
        else:
            self.add_to_output("Instrument is not connected.")

    def query_rst(self):
        if self.instrument:
            try:
                self.instrument.write("*RST")
                self.add_to_output("Instrument reset.")
                # Delay to allow the instrument to initialize after reset
                QTimer.singleShot(1000, self.post_reset_initialization)
            except Exception as e:
                self.add_to_output(f"Error resetting instrument: {str(e)}")
        else:
            self.add_to_output("Instrument is not connected.")

    def post_reset_initialization(self):
        # Check protection statuses after reset
        self.check_protection_statuses()

        # Turn on each selected channel dynamically
        for channel in self.selected_channels:
            self.turn_channel_on(channel)
    def apply_settings(self, channel):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        try:
            # Get entries for voltage and current
            voltage_entry = self.channel_settings[channel]['voltage_entry']
            current_entry = self.channel_settings[channel]['current_entry']
            slew_rate_entry = self.channel_settings[channel]['slew_entry']

            # Read and strip the text values
            voltage = voltage_entry.text().strip() if voltage_entry else ""
            current = current_entry.text().strip() if current_entry else ""
            slew_rate = slew_rate_entry.text().strip() if slew_rate_entry else ""

            # Apply voltage settings if provided
            if voltage:
                self.instrument.write(f"VOLT {voltage}, (@{channel})")
                self.add_to_output(f"Voltage set to {voltage} V for Channel {channel}")

            # Apply current settings if provided
            if current:
                self.instrument.write(f"CURR {current}, (@{channel})")
                self.add_to_output(f"Current set to {current} A for Channel {channel}")

            # Apply slew rate settings if provided
            if slew_rate:
                self.instrument.write(f"VOLT:SLEW {slew_rate}, (@{channel})")
                self.add_to_output(f"Slew rate set to {slew_rate} V/s for Channel {channel}")

            # After applying settings, check protection statuses quickly
            QTimer.singleShot(2000, lambda: self.check_protection_statuses())
        except KeyError as e:
            self.add_to_output(f"Key error in accessing channel settings: {str(e)}")
        except Exception as e:
            self.add_to_output(f"Error applying settings for channel {channel}: {str(e)}")

    def setup_channel_controls(self):
        self.channel_layout = QGridLayout()
        for i in range(1, 5):
            self.add_channel_ui(i)
            self.channel_settings[i]['apply_button'].clicked.connect(lambda _, ch=i: self.get_slew_rate(ch))
        self.dialog_layout.addLayout(self.channel_layout)

    def read_channel_settings(self, channel):
        if self.instrument:
            try:
                voltage = self.instrument.query(f"MEAS:VOLT? (@{channel})")
                current = self.instrument.query(f"MEAS:CURR? (@{channel})")
                self.channel_settings[channel]['voltage'].append(float(voltage))
                self.channel_settings[channel]['current'].append(float(current))
                self.add_to_output(f"Channel {channel} Voltage: {voltage} V, Current: {current} A")
            except Exception as e:
                self.add_to_output(f"Error reading settings for channel {channel}: " + str(e))
        else:
            self.add_to_output("Instrument is not connected.")

    def update_live_data(self):
        if self.instrument is None:
            return

        for channel in self.selected_channels:  # Only update for selected channels
            if self.channel_settings[channel]['status']:
                self.monitor_channel(channel)
            try:
                voltage = float(self.instrument.query(f"MEAS:VOLT? (@{channel})"))
                current = float(self.instrument.query(f"MEAS:CURR? (@{channel})"))
                self.channel_settings[channel]['voltage_led'].setText(f"{voltage:.3f} V")
                self.channel_settings[channel]['current_led'].setText(f"{current:.3f} A")

                # Log the data as it's updated on the GUI
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                self.log_data_to_csv(channel, now, voltage, current)

            except pyvisa.VisaIOError as e:
                self.add_to_output(f"Error updating live data for channel {channel}: {str(e)}")

    def start_monitoring(self, channel):
        if channel in self.selected_channels and channel not in self.monitoring_threads:
            self.thread_control[channel] = True
            self.monitoring_threads[channel] = threading.Thread(target=self.monitor_channel, args=(channel,),
                                                                daemon=True)
            self.monitoring_threads[channel].start()

    def stop_monitoring(self, channel):
        if channel in self.monitoring_threads:
            self.thread_control[channel] = False
            del self.monitoring_threads[channel]

    def monitor_channel(self, channel):
        while self.thread_control.get(channel, False):
            if self.instrument:
                try:
                    voltage = self.instrument.query(f"MEAS:VOLT? (@{channel})")
                    current = self.instrument.query(f"MEAS:CURR? (@{channel})")
                    status_text = "on" if self.channel_settings[channel]['status'] else "off"
                    self.update_channel_ui(channel, voltage, current, status_text)
                    time.sleep(1)
                    if voltage == 0.0:  # Check for sudden voltage drop to zero
                        self.check_protection_statuses()
                except pyvisa.VisaIOError as e:
                    self.add_to_output(f"Error reading from channel {channel}: {e}")
                    time.sleep(1)
            else:
                break  # Stop monitoring if disconnected

    def setup_output_window(self):
        self.output_window = QTextEdit()
        self.output_window.setReadOnly(True)
        self.dialog_layout.addWidget(self.output_window)

    def get_slew_rate(self, channel, update_led=True):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        try:
            response = self.instrument.query(f"VOLT:SLEW? (@{channel})")
            slew_rate = float(response)
            # Round the slew rate to 2 decimal places before displaying
            rounded_slew_rate = round(slew_rate, 2)
            self.add_to_output(f"Channel {channel} Slew Rate: {rounded_slew_rate} V/s")

            if update_led:
                led = self.channel_settings[channel].get('slew_led', None)
                if led:
                    led.setText(f"{rounded_slew_rate} V/s")
                else:
                    self.add_to_output("Error: Slew LED is None")

        except Exception as e:
            self.add_to_output(f"Error reading slew rate for channel {channel}: {str(e)}")

    def update_channel_ui(self, channel, voltage, current, status_text):
        # Update UI components based on the received data
        self.channel_settings[channel]['voltage_led'].setText(f"{float(voltage):.3f} V")
        self.channel_settings[channel]['current_led'].setText(f"{float(current):.3f} A")
        self.channel_settings[channel]['status_label'].setText(f"Status: {status_text}")

        # Update OVP and OCP indicators based on received data
        if "OVP" in voltage:
            self.channel_settings[channel]['ovp_indicator'].setStyleSheet("background-color: red;")
        else:
            self.channel_settings[channel]['ovp_indicator'].setStyleSheet("background-color: green;")

        if "OCP" in current:
            self.channel_settings[channel]['ocp_indicator'].setStyleSheet("background-color: red;")
        else:
            self.channel_settings[channel]['ocp_indicator'].setStyleSheet("background-color: green;")

    def query_initial_channel_statuses(self):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        self.add_to_output(f"Selected channels for querying status: {self.selected_channels}")

        try:
            for channel in self.selected_channels:
                try:
                    self.add_to_output(f"Querying status for Channel {channel}...")
                    response = self.instrument.query(f"OUTPut:STATe? (@{channel})").strip()
                    state = "ON" if response == '1' else "OFF"
                    self.channel_settings[channel]['status'] = (state == "ON")
                    self.update_ui_channel_status(channel, state)
                    self.add_to_output(f"Channel {channel} is currently {state}.")
                    if state == "ON":
                        self.channel_settings[channel]['graph_button'].setEnabled(True)
                except pyvisa.errors.VisaIOError as e:
                    # Handling specific timeout error
                    if e.error_code == pyvisa.constants.VI_ERROR_TMO:
                        self.add_to_output(
                            f"Timeout error when querying status of Channel {channel}. It may not be present or not responding.")
                    else:
                        self.add_to_output(f"Error querying status for Channel {channel}: {str(e)}")
        except Exception as e:
            self.add_to_output(f"Unexpected error when querying channel statuses: {str(e)}")

    def ensure_csv_exists(self):
        # Ensure the CSV file exists with proper headers before attempting to read it
        csv_file = "power_supply_data.csv"
        if not os.path.exists(csv_file):
            with open(csv_file, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Channel", "Time", "Voltage", "Current"])  # Write header



    def setup_plot(self):
        plot = pg.PlotWidget()
        voltage_curve = plot.plot(pen='r')
        current_curve = plot.plot(pen='b')

        # Enable grid lines on both axes
        plot.showGrid(x=True, y=True, alpha=0.3)  # alpha controls the transparency of the grid lines

        return plot, voltage_curve, current_curve

    def highlight_value(self, plot, time, voltage, current):
        # Function to highlight or mark a specific point on the graph
        voltage_mark = pg.PlotDataItem([time], [voltage], symbol='o', symbolSize=10, symbolBrush=('r'))
        current_mark = pg.PlotDataItem([time], [current], symbol='o', symbolSize=10, symbolBrush=('b'))
        plot.addItem(voltage_mark)
        plot.addItem(current_mark)

    def show_live_graph_old(self, channel):
        if channel in self.selected_channels and channel in self.graph_dialogs:
            graph_dialog = QDialog(self.dialog)
            graph_dialog.setWindowTitle(f"Channel {channel} Data")
            layout = QVBoxLayout()

            plot = pg.PlotWidget(title="Voltage and Current vs Time")
            plot.addLegend()
            voltage_curve = plot.plot(pen='r', name='Voltage')
            current_curve = plot.plot(pen='g', name='Current')
            plot.setLabel('left', 'Value')
            plot.setLabel('bottom', 'Time', units='s')

            layout.addWidget(plot)
            graph_dialog.setLayout(layout)

            self.ensure_csv_exists()  # Ensure CSV is available before starting the timer

            update_timer = QTimer()
            update_timer.timeout.connect(lambda: self.update_plot(plot, voltage_curve, current_curve, channel))
            update_timer.start(1000)  # Update plot every second

            graph_dialog.exec_()

    def update_plot(self, plot, voltage_curve, current_curve, channel):
        csv_file = "power_supply_data.csv"
        try:
            with open(csv_file, 'r') as file:
                reader = csv.reader(file)
                next(reader)  # Skip header
                data = [row for row in reader if row[0].isdigit() and int(row[0]) == channel]

            if not data:
                print(f"No data for channel {channel}.")
                return

            base_time = datetime.datetime.strptime(data[0][1], '%Y-%m-%d %H:%M:%S')
            time_seconds = [(datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S') - base_time).total_seconds() for row in data]
            voltage = [float(row[2]) for row in data]
            current = [float(row[3]) for row in data]

            voltage_curve.setData(time_seconds, voltage, pen='r')
            current_curve.setData(time_seconds, current, pen='b')

            plot.setTitle(f"Latest Voltage: {voltage[-1]:.3f} V, Current: {current[-1]:.3f} A")

            # Manage markers
            if self.last_markers[channel]['voltage']:
                plot.removeItem(self.last_markers[channel]['voltage'])
            if self.last_markers[channel]['current']:
                plot.removeItem(self.last_markers[channel]['current'])

            self.last_markers[channel]['voltage'] = pg.PlotDataItem([time_seconds[-1]], [voltage[-1]], symbol='o', symbolSize=15, symbolBrush='y')
            self.last_markers[channel]['current'] = pg.PlotDataItem([time_seconds[-1]], [current[-1]], symbol='o', symbolSize=15, symbolBrush='y')
            plot.addItem(self.last_markers[channel]['voltage'])
            plot.addItem(self.last_markers[channel]['current'])

            # Adjust plot to center on the latest data point
            current_view_range = plot.viewRange()
            x_range_width = current_view_range[0][1] - current_view_range[0][0]
            new_x_range = [time_seconds[-1] - x_range_width / 2, time_seconds[-1] + x_range_width / 2]
            plot.setXRange(*new_x_range, padding=0)

            if True:  # Replace with dynamic condition if needed
                plot.showGrid(x=True, y=True, alpha=0.3)
            else:
                plot.showGrid(x=False, y=False)
        except FileNotFoundError:
            print(f"CSV file {csv_file} not found.")
        except Exception as e:
            print(f"Error reading from CSV file: {e}")
    def show_live_graph(self, channel):
        if channel not in self.graph_dialogs:
            graph_window = QWidget()
            graph_window.setWindowTitle(f"Channel {channel} Data")
            layout = QVBoxLayout(graph_window)

            plot = pg.PlotWidget(title="Voltage and Current vs Time")
            voltage_curve = plot.plot(pen='r', name='Voltage')
            current_curve = plot.plot(pen='b', name='Current')
            plot.addLegend()
            plot.setLabel('left', 'Value')
            plot.setLabel('bottom', 'Time', units='s')

            layout.addWidget(plot)
            graph_window.setLayout(layout)
            graph_window.resize(600, 600)

            self.graph_dialogs[channel] = graph_window
            self.last_markers[channel] = {'voltage': None, 'current': None}
            timer = QTimer()
            # Connect the plot and curves correctly
            timer.timeout.connect(lambda ch=channel, p=plot, vc=voltage_curve, cc=current_curve: self.update_plot(p, vc, cc, ch))
            timer.start(1000)  # Update plot every second
            self.update_timers[channel] = timer
        else:
            graph_window = self.graph_dialogs[channel]

        graph_window.show()
        graph_window.raise_()
        graph_window.activateWindow()

    def fetch_measurements(self, channel):
        if not self.instrument:
            self.add_to_output("Instrument is not connected.")
            return

        try:
            # Fetching voltage
            voltage = self.instrument.query(f"MEASure:ARRay:VOLTage:DC? (@{channel})")
            self.channel_settings[channel]['voltage_led'].setText(f"{voltage} V")
            self.add_to_output(f"Channel {channel} Voltage: {voltage} V")

            # Fetching current
            current = self.instrument.query(f"MEASure:ARRay:CURRent:DC? (@{channel})")
            self.channel_settings[channel]['current_led'].setText(f"{current} A")
            self.add_to_output(f"Channel {channel} Current: {current} A")

            # Fetching power if applicable
            power = self.instrument.query(f"MEASure:ARRay:POWer:DC? (@{channel})")
            self.add_to_output(f"Channel {channel} Power: {power} W")

        except Exception as e:
            self.add_to_output(f"Error fetching measurements for channel {channel}: {str(e)}")

    def update_ui_channel_status(self, channel, state):
        """
        Updates the UI components based on the channel status.
        """
        button = self.channel_settings[channel]['turn_on_button']
        if button:
            button.setText("Turn Off" if state == "ON" else "Turn On")
            button.setStyleSheet("background-color: red;" if state == "ON" else "background-color: lightgreen;")
        else:
            self.add_to_output(f"UI element for channel {channel} status button not found.")

    def log_data_to_csv(self, channel, time, voltage, current):
        # Append data to CSV file
        with open("power_supply_data.csv", 'a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([channel, time, voltage, current])

    def fetch_measurements_and_log(self, channel):
        # Example function that might fetch measurements and then log them
        # Simulating data fetching here
        time = 10.5  # Simulated time value
        voltage = 3.2  # Simulated voltage value
        current = 1.5  # Simulated current value
        self.log_data_to_csv(channel, time, voltage, current)

    def set_ovp(self, channel):
        try:
            ovp_level = float(QInputDialog.getText(self.dialog, "Set OVP", "Enter OVP Level (V):")[0])
            self.instrument.write(f"VOLT:PROT {ovp_level}, (@{channel})")
            self.add_to_output(f"Set OVP level to {ovp_level} V for Channel {channel}")
        except ValueError:
            self.add_to_output("Invalid OVP value entered.")
        except pyvisa.VisaIOError as e:
            self.add_to_output(f"Failed to set OVP for Channel {channel}: {str(e)}")

    def set_ocp(self, channel):
        try:
            ocp_status = QInputDialog.getItem(self.dialog, "Set OCP", "Enable OCP?", ["ON", "OFF"], 0, False)[0]
            self.instrument.write(f"CURR:PROT:STAT {ocp_status}, (@{channel})")
            if ocp_status == "ON":
                ocp_delay = float(QInputDialog.getText(self.dialog, "Set OCP Delay", "Enter OCP Delay (s):")[0])
                self.instrument.write(f"CURR:PROT:DEL {ocp_delay}, (@{channel})")
            self.add_to_output(f"Set OCP to {ocp_status} with delay {ocp_delay}s for Channel {channel}")
        except ValueError:
            self.add_to_output("Invalid OCP delay value entered.")
        except pyvisa.VisaIOError as e:
            self.add_to_output(f"Failed to set OCP for Channel {channel}: {str(e)}")

    def clear_protection(self, channel):
        try:
            self.instrument.write(f"OUTP:PROT:CLE, (@{channel})")
            self.add_to_output(f"Cleared protection for Channel {channel}")
        except pyvisa.VisaIOError as e:
            self.add_to_output(f"Failed to clear protection for Channel {channel}: {str(e)}")

    def update_channel_name_ui(self, channel, new_name):
        # Correct the attribute name here
        label = self.channel_labels.get(channel)
        if label:
            label.setText(new_name)

    def cleanup_on_exit(self):
        # Perform any cleanup needed before application exit
        if self.instrument:
            self.disconnect_instrument()  # Assuming this method safely disconnects the instrument


def main():
    app = QApplication(sys.argv)
    dialog = QDialog()
    control_panel = PowerSupplyControlPanel(dialog)
    dialog.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
    print("debug")
