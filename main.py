import logging

from application.logic.app_logic import ApplicationLogic
from application.logic.cli_handler import parse_and_validate_args

def run_gui():
    """Initializes and runs the graphical user interface."""
    from application.gui_components import GUI, show_splash_during_init

    def init_app_logic():
        return ApplicationLogic(is_cli=False)

    core_app = show_splash_during_init(init_app_logic)
    gui = GUI(app_logic=core_app)
    core_app.gui_instance = gui
    gui.run()

def run_cli(args):
    """Runs the application in command-line interface mode."""
    logger = logging.getLogger(__name__)
    logger.info("--- FunGen CLI Mode ---")
    core_app = ApplicationLogic(is_cli=True)
    core_app.run_cli(args)
    logger.info("--- CLI Task Finished ---")

def main():
    """
    Main function to run the application.
    This function handles dependency checking, argument parsing, and starts either the GUI or CLI.
    """
    # Step 1: Set up core environment (logging, multiprocessing, etc.)
    ApplicationLogic.setup_core_environment()
    logger = logging.getLogger(__name__)

    # Step 2: Parse and validate command-line arguments
    args = parse_and_validate_args()

    # Step 3: Start the appropriate interface
    if args.input_path:
        run_cli(args)
    else:
        run_gui()

if __name__ == "__main__":
    main()