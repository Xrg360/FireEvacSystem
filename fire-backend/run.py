"""Development server:  python run.py   (API + Socket.IO + in-process engine on :5000)

Production (Docker) uses gunicorn:  gunicorn -w 1 --threads 100 -b 0.0.0.0:5000 wsgi:app
"""

import os

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    # 0.0.0.0 so phones on the same Wi-Fi can reach the laptop
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
