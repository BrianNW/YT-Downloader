import threading
import webbrowser

from app import app


def run_server() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    webbrowser.open("http://127.0.0.1:5000")
    server_thread.join()
