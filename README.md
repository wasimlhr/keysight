# keysight
Keysight Power Supply
Keysight/Agilent Power Supply Controller
This project provides a graphical user interface (GUI) tool for controlling all Keysight/Agilent N67XX series power supplies. The application enables users to manage multiple channels, monitor real-time data, apply various settings, and capture screenshots of the power supply's GUI.

Getting Started
These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.


**GUI**


![image](https://github.com/wasimlhr/keysight/assets/142178067/236fdbc6-c02a-4df7-a50a-d40ca1e65d56)

Prerequisites
You need Python 3.8 or higher installed on your machine, along with the PyQt5, pyqtgraph, and PyVISA libraries for the GUI and instrument communication.

bash
Copy code
# Install the necessary Python packages
pip install pyqt5 pyqtgraph pyvisa
Installation
Clone the repository and run the application:

bash
Copy code
# Clone the repository
git clone https://github.com/wasimlhr/keysight-power-supply-controller.git
cd keysight-power-supply-controller

# Run the application
python control_panel.py
Compiling to Executable
To compile the project into a standalone executable file for Windows, use PyInstaller:

bash
Copy code
# Install PyInstaller
pip install pyinstaller

# Navigate to the project directory if not already there
cd keysight-power-supply-controller

# Use PyInstaller to create a single executable
pyinstaller --onefile --windowed keysight_gui.py
This command will generate a dist folder containing the keysight_gui.exe executable that can be run on any Windows machine without needing a Python installation.

Usage
Ensure your Keysight/Agilent power supply is network-connected or directly connected to your computer. Launch the application, enter the IP address of the N6705B mainframe, and use the GUI to interact with the power supply.

Features
Real-time Monitoring: View real-time voltage and current measurements for each channel.
Configuration Controls: Adjust voltage, current, and protection settings via an intuitive interface.
Screenshot Functionality: Capture and save the current state of the GUI, useful for documentation or troubleshooting.
Contributing
Contributions are welcome! Please read CONTRIBUTING.md for details on our code of conduct, and the process for submitting pull requests.

Versioning
For the versions available, see the tags on this repository.

Authors
Wasim - Initial work - wasimlhr

Acknowledgments
Keysight Technologies for specifications of the N67XX series power supplies.
The PyQt and PyVISA communities for their invaluable libraries.
