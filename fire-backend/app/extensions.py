from flask_socketio import SocketIO

# async_mode "threading" + simple-websocket: real WebSockets without gevent monkey patching,
# which keeps psycopg, numpy and scikit-learn safe to use in the same process.
socketio = SocketIO(async_mode="threading")
