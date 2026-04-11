
import threading
import webbrowser
import sys
import traceback
import logging
from app import app

import time

def run_server(error_event):
    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    except Exception as e:
        logging.exception("Exception in Flask server thread:")
        error_event.set()

def wait_for_exit():
    input("\nPress Enter to exit...")

def main():
    # Set up logging to file
    logging.basicConfig(
        filename="desktop_app.log",
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s"
    )
    # Also log uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback))
        print("An error occurred. See desktop_app.log for details.")
        wait_for_exit()
        sys.exit(1)
    sys.excepthook = handle_exception

    error_event = threading.Event()
    try:
        server_thread = threading.Thread(target=run_server, args=(error_event,), daemon=True)
        server_thread.start()
        webbrowser.open("http://127.0.0.1:5000")

        # Monitor for server errors or user exit
        while server_thread.is_alive():
            if error_event.is_set():
                print("\nA server error occurred. See desktop_app.log for details.")
                break
            time.sleep(0.5)

        # At this point, the server thread has exited (either normally or due to error)
        if not error_event.is_set():
            print("\nThe server has stopped running.")
    except Exception:
        logging.exception("Exception in main thread:")
        print("An error occurred. See desktop_app.log for details.")
    finally:
        wait_for_exit()

if __name__ == "__main__":
    main()
